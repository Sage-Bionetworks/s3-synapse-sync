# render_jpg.py
from __future__ import print_function, division
import itertools
import pathlib
import json
import os
# Opener
import zarr
import numpy as np
from PIL import Image
from matplotlib import colors
from tifffile import TiffFile
from openslide import OpenSlide
from openslide.deepzoom import DeepZoomGenerator
# main
import re
import logging
import argparse
from json.decoder import JSONDecodeError

'''
    # render_jpg.py
'''

def composite_channel(target, image, color, range_min, range_max):
    ''' Render _image_ in pseudocolor and composite into _target_
    Args:
        target: Numpy float32 array containing composition target image
        image: Numpy uint16 array of image to render and composite
        color: Color as r, g, b float array, 0-1
        range_min: Threshhold range minimum, 0-65535
        range_max: Threshhold range maximum, 0-65535
    '''
    f_image = (image.astype('float32') - range_min) / (range_max - range_min)
    f_image = f_image.clip(0,1, out=f_image)
    for i, component in enumerate(color):
        target[:, :, i] += f_image * component


def _calculate_total_tiles(opener, tile_size, num_levels):
    tiles = 0
    for level in range(num_levels):
        (nx, ny) = opener.get_level_tiles(level, tile_size)
        tiles += nx * ny

    return tiles

def render_color_tiles(opener, output_dir, tile_size, config_rows, logger, progress_callback=None):
    EXT = 'jpg'

    for settings in config_rows:
        settings['Source'] = opener.path

    print('Processing:', str(opener.path))

    output_path = pathlib.Path(output_dir)

    if not output_path.exists():
        output_path.mkdir(parents=True)

    num_levels = opener.get_shape()[1]

    total_tiles = _calculate_total_tiles(opener, tile_size, num_levels)
    progress = 0

    if num_levels < 2:
        logger.warning(f'Number of levels {num_levels} < 2')

    for level in range(num_levels):

        (nx, ny) = opener.get_level_tiles(level, tile_size)
        print('    level {} ({} x {})'.format(level, ny, nx))

        for ty, tx in itertools.product(range(0, ny), range(0, nx)):

            filename = '{}_{}_{}.{}'.format(level, tx, ty, EXT)

            for settings in config_rows:

                group_dir = settings['Group Path'] 
                if not (output_path / group_dir).exists():
                    (output_path / group_dir).mkdir(parents=True)
                output_file = str(output_path / group_dir / filename)

                try:
                    opener.save_tile(output_file, settings, tile_size, level, tx, ty)
                except AttributeError as e:
                    logger.error(f'{level} ty {ty} tx {tx}: {e}')

                progress += 1
                if progress_callback is not None:
                    progress_callback(progress, len(config_rows)*total_tiles)

'''
    # Opener
'''

def check_ext(path):
    base, ext1 = os.path.splitext(path)
    ext2 = os.path.splitext(base)[1]
    return ext2 + ext1

class Opener:

    def __init__(self, path):
        self.warning = ''
        self.path = path
        self.tilesize = 1024
        ext = check_ext(path)

        if ext == '.ome.tif' or ext == '.ome.tiff':
            self.io = TiffFile(self.path, is_ome=False)
            self.group = zarr.open(self.io.series[0].aszarr())
            self.reader = 'tifffile'
            self.ome_version = self._get_ome_version()
            print("OME ", self.ome_version)
            num_channels = self.get_shape()[0]
            tile_0 = self.get_tifffile_tile(num_channels, 0,0,0,0)
            if (num_channels == 3 and tile_0.dtype == 'uint8'):
                self.rgba = True
                self.rgba_type = '3 channel'
            elif (num_channels == 1 and tile_0.dtype == 'uint8'):
                self.rgba = True
                self.rgba_type = '1 channel'
            else:
                self.rgba = False
                self.rgba_type = None

        else:
            self.io = OpenSlide(self.path)
            self.dz = DeepZoomGenerator(self.io, tile_size=1024, overlap=0, limit_bounds=True) 
            self.reader = 'openslide'
            self.rgba = True
            self.rgba_type = None

        print("RGB ", self.rgba)
        print("RGB type ", self.rgba_type)

    def _get_ome_version(self):
        try:
            software = self.io.pages[0].tags[305].value
            sub_ifds = self.io.pages[0].tags[330].value
            if "Faas" in software or sub_ifds is None:
                return 5

            m = re.search('OME\\sBio-Formats\\s(\\d+)\\.\\d+\\.\\d+', software)
            if m is None:
                return 5
            return int(m.group(1))
        except Exception as e:
            print(e)
            return 5

    def close(self):
        self.io.close()

    def is_rgba(self, rgba_type=None):
        if rgba_type is None:
            return self.rgba
        else:
            return self.rgba and rgba_type == self.rgba_type

    def get_level_tiles(self, level, tile_size):
        if self.reader == 'tifffile':

            # Negative indexing to support shape len 3 or len 2
            ny = int(np.ceil(self.group[level].shape[-2] / tile_size))
            nx = int(np.ceil(self.group[level].shape[-1] / tile_size))
            print((nx, ny))
            return (nx, ny)
        elif self.reader == 'openslide':
            l = self.dz.level_count - 1 - level
            return self.dz.level_tiles[l]

    def get_shape(self):
        if self.reader == 'tifffile':

            num_levels = len(self.group)
            shape = self.group[0].shape
            if len(shape) == 3:
                (num_channels, shape_y, shape_x) = shape
            else:
                (shape_y, shape_x) = shape
                num_channels = 1
            return (num_channels, num_levels, shape_x, shape_y)

        elif self.reader == 'openslide':

            (width, height) = self.io.dimensions

            def has_one_tile(counts):
                return max(counts) == 1

            small_levels = list(filter(has_one_tile, self.dz.level_tiles))
            level_count = self.dz.level_count - len(small_levels) + 1

            return (3, level_count, width, height)

    def read_tiles(self, level, channel_number, tx, ty, tilesize):
        ix = tx * tilesize
        iy = ty * tilesize

        num_channels = self.get_shape()[0]
        try:
            if num_channels == 1:
                tile = self.group[level][iy:iy+tilesize, ix:ix+tilesize]
            else:
                tile = self.group[level][channel_number, iy:iy+tilesize, ix:ix+tilesize]
            tile = np.squeeze(tile)
            return tile
        except Exception as e:
            G['logger'].error(e)
            return None

    def get_tifffile_tile(self, num_channels, level, tx, ty, channel_number, tilesize=None):

        if self.reader == 'tifffile':

            self.tilesize = max(self.io.series[0].pages[0].chunks)

            if (tilesize is None) and self.tilesize == 0:
                # Warning... return untiled planes as all-black
                self.tilesize = 1024
                self.warning = f'Level {level} is not tiled. It will show as all-black.'
                tile = np.zeros((1024, 1024), dtype=ifd.dtype)

            elif (tilesize is not None) and self.tilesize == 0:
                self.tilesize = tilesize
                tile = self.read_tiles(level, channel_number, tx, ty, tilesize)

            elif (tilesize is not None) and (self.tilesize != tilesize):
                tile = self.read_tiles(level, channel_number, tx, ty, tilesize)

            else:
                self.tilesize = self.tilesize if self.tilesize else 1024
                tile = self.read_tiles(level, channel_number, tx, ty, self.tilesize)

            if tile is None:
                return None

            return tile

    def get_tile(self, num_channels, level, tx, ty, channel_number, fmt=None):
        
        if self.reader == 'tifffile':
 
            if self.is_rgba('3 channel'):
                tile_0 = self.get_tifffile_tile(num_channels, level, tx, ty, 0)
                tile_1 = self.get_tifffile_tile(num_channels, level, tx, ty, 1)
                tile_2 = self.get_tifffile_tile(num_channels, level, tx, ty, 2)
                tile = np.zeros((tile_0.shape[0], tile_0.shape[1], 3), dtype=np.uint8)
                tile[:, :, 0] = tile_0
                tile[:, :, 1] = tile_1
                tile[:, :, 2] = tile_2
                format = 'I;8'
            else:
                tile = self.get_tifffile_tile(num_channels, level, tx, ty, channel_number)
                format = fmt if fmt else 'I;16'

                if (tile.dtype != np.uint16):
                    if tile.dtype == np.uint8:
                        tile = 255 * tile.astype(np.uint16)
                    else:
                        tile = tile.astype(np.uint16)

            return Image.fromarray(tile, format)

        elif self.reader == 'openslide':
            l = self.dz.level_count - 1 - level
            img = self.dz.get_tile(l, (tx, ty))
            return img

    def save_tile(self, output_file, settings, tile_size, level, tx, ty, is_mask=False):
        if self.reader == 'tifffile' and self.is_rgba('3 channel'):

            num_channels = self.get_shape()[0]
            tile_0 = self.get_tifffile_tile(num_channels, level, tx, ty, 0, tile_size)
            tile_1 = self.get_tifffile_tile(num_channels, level, tx, ty, 1, tile_size)
            tile_2 = self.get_tifffile_tile(num_channels, level, tx, ty, 2, tile_size)
            tile = np.zeros((tile_0.shape[0], tile_0.shape[1], 3), dtype=np.uint8)
            tile[:,:,0] = tile_0
            tile[:,:,1] = tile_1
            tile[:,:,2] = tile_2

            img = Image.fromarray(tile, 'RGB')
            img.save(output_file, quality=85)

        elif self.reader == 'tifffile' and self.is_rgba('1 channel'):

            num_channels = self.get_shape()[0]
            tile = self.get_tifffile_tile(num_channels, level, tx, ty, 0, tile_size)

            img = Image.fromarray(tile, 'RGB')
            img.save(output_file, quality=85)

        elif self.reader == 'tifffile' and is_mask:
            color = settings['Color'][0]
            num_channels = self.get_shape()[0]
            tile = self.get_tifffile_tile(num_channels, level, tx, ty, 0, tile_size)
            target = np.zeros(tile.shape + (4,), np.uint8)
            colorize_mask(
                target, tile, colors.to_rgb(color)
            )
            img = Image.frombytes('RGBA', target.T.shape[1:], target.tobytes())
            img.save(output_file, quality=85)

        elif self.reader == 'tifffile' and not is_mask:
            for i, (marker, color, start, end) in enumerate(zip(
                    settings['Channel Number'], settings['Color'],
                    settings['Low'], settings['High']
            )):
                num_channels = self.get_shape()[0]
                tile = self.get_tifffile_tile(num_channels, level, tx, ty, int(marker), tile_size)
                
                if (tile.dtype != np.uint16):
                    if tile.dtype == np.uint8:
                        tile = 255 * tile.astype(np.uint16)
                    else:
                        tile = tile.astype(np.uint16)

                if i == 0:
                    target = np.zeros(tile.shape + (3,), np.float32)

                composite_channel(
                    target, tile, colors.to_rgb(color), float(start), float(end)
                )

            np.clip(target, 0, 1, out=target)
            target_u8 = (target * 255).astype(np.uint8)
            img = Image.frombytes('RGB', target.T.shape[1:], target_u8.tobytes())
            img.save(output_file, quality=85)

        elif self.reader == 'openslide':
            l = self.dz.level_count - 1 - level
            img = self.dz.get_tile(l, (tx, ty))
            img.save(output_file, quality=85)

'''
    # main
'''

def label_to_dir(s, empty='0'):
    replaced = re.sub('[^0-9a-zA-Z _-]+', '', s).strip()
    replaced = replaced.replace(' ','_')
    replaced = replaced.replace('_','-')
    replaced = re.sub('-+', '-', replaced)
    return empty if replaced == '' else replaced

def deduplicate(data_name, data_dict, data_dir):
    """
    Return a local path for given data path
    Args:
        data_name: the basename of the target file
        data_dict: the existing mapping of local paths
        data_dir: the full path of the destination directory
    """
    n_dups = 0
    basename = data_name
    local_path = os.path.join(data_dir, basename)
    while local_path in data_dict.values():
        root, ext = os.path.splitext(basename) 
        local_path = os.path.join(data_dir, f'{root}-{n_dups}{ext}')
        n_dups += 1
    return local_path

def deduplicate_dicts(dicts, data_dir='', in_key='label', out_key='label', is_dir=False):
    """
    Map dictionaries by key to unique labels 
    Args:
        dicts: list of dicts containing input key and output key 
        data_dir: the full path of the destination directory
        in_key: used for key of output dictionary
        out_key: used for values of output dictionary
        is_dir: set true if unique labels must be directories
    """
    data_dict = dict()
    for d in dicts:
        data_in = d[in_key]
        data_name = label_to_dir(d[out_key]) if is_dir else d[out_key]
        data_dict[data_in] = deduplicate(data_name, data_dict, data_dir)

    return data_dict

def dedup_label_to_path(dicts, data_dir=''):
    return deduplicate_dicts(dicts, data_dir, 'label', 'label', True)
  
def group_path_from_label(group_data, label, data_dir=''):
    return dedup_label_to_path(group_data, data_dir)[label]

def make_group_path(groups, group):
    c_path = '--'.join(
        str(c['id']) + '__' + label_to_dir(c['label'])
        for c in group['channels']
    )
    g_path = group_path_from_label(groups, group['label'])
    return  g_path + '_' + c_path

def make_rows(d):
    for group in d:
        channels = group['channels']
        yield {
            'Group Path': make_group_path(d, group), 
            'Channel Number': [str(c['id']) for c in channels],
            'Low': [int(65535 * c['min']) for c in channels],
            'High': [int(65535 * c['max']) for c in channels],
            'Color': ['#' + c['color'] for c in channels]
        }

def render(opener, saved, output_dir, logger):
    config_rows = list(make_rows(saved['groups']))
    render_color_tiles(opener, output_dir, 1024, config_rows, logger)

def format_arrow(a):
    return {
        'Text': a['text'],
        'HideArrow': a['hide'],
        'Point': a['position'],
        'Angle': 60 if a['angle'] == '' else a['angle']
    }

def format_overlay(o):
    return {
        'x': o[0],
        'y': o[1],
        'width': o[2],
        'height': o[3]
    }

def make_waypoints(d):

    for waypoint in d:
        wp = {
            'Name': waypoint['name'],
            'Description': waypoint['text'],
            'Arrows': list(map(format_arrow, waypoint['arrows'])),
            'Overlays': list(map(format_overlay, waypoint['overlays'])),
            'Group': waypoint['group'],
            'Masks': [],
            'ActiveMasks': [],
            'Zoom': waypoint['zoom'],
            'Pan': waypoint['pan'],
        }

        yield wp

def make_stories(d):
    return [{
        'Name': '',
        'Description': '',
        'Waypoints': list(make_waypoints(d))
    }]

def make_groups(d):
    for group in d:
        yield {
            'Name': group['label'],
            'Path': make_group_path(d, group),
            'Colors': [c['color'] for c in group['channels']],
            'Channels': [c['label'] for c in group['channels']]
        }

def make_exhibit_config(opener, root_url, saved):

    (num_channels, num_levels, width, height) = opener.get_shape()

    return {
        'Images': [{
            'Name': 'i0',
            'Description': saved['sample_info']['name'],
            'Path': root_url if root_url else '.',
            'Width': width,
            'Height': height,
            'MaxLevel': num_levels - 1
        }],
        'Header': saved['sample_info']['text'],
        'Rotation': saved['sample_info']['rotation'],
        'Layout': {'Grid': [['i0']]},
        'Stories': make_stories(saved['waypoints']),
        'Groups': list(make_groups(saved['groups'])),
        'Masks': []
    }

def main(ome_tiff, author_json, output_dir, root_url, force=False):
   FORMATTER = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
   logger = logging.getLogger('app')
   ch = logging.StreamHandler()
   ch.setLevel(logging.DEBUG)
   ch.setFormatter(FORMATTER)
   logger.addHandler(ch)
   
   opener = None
   saved = None

   try:
      opener = Opener(ome_tiff)
   except (FileNotFoundError, TiffFileError) as e:
       logger.error(e)
       logger.error(f'Invalid ome-tiff file: cannot parse {ome_tiff}')
       return

   try: 
       with open(author_json) as json_file:
           saved = json.load(json_file)
       groups = saved['groups']
   except (FileNotFoundError, JSONDecodeError, KeyError) as e:
       logger.error(e)
       logger.error(f'Invalid save file: cannot parse {json_file}')
       return

   if not force and os.path.exists(output_dir):
      logger.error(f'Refusing to overwrite output directory {output_dir}')
      return
   elif force and os.path.exists(output_dir):
      logger.warning(f'Writing to existing output directory {output_dir}')

   output_path = pathlib.Path(output_dir)
   if not output_path.exists():
        output_path.mkdir(parents=True)

   exhibit_config = make_exhibit_config(opener, root_url, saved)

   with open(output_dir / 'exhibit.json', 'w') as wf:
       json_text = json.dumps(exhibit_config, ensure_ascii=False)
       wf.write(json_text)

   render(opener, saved, output_dir, logger)

if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "ome_tiff", metavar="ome_tiff", type=pathlib.Path,
        help="Input path to OME-TIFF with all channel groups",
    )
    parser.add_argument(
        "author_json", metavar="author_json", type=pathlib.Path,
        help="Input Minerva Author save file with channel configuration",
    )
    parser.add_argument(
        "output_dir", metavar="output_dir", type=pathlib.Path,
        help="Output directory for rendered JPEG pyramid",
    )
    parser.add_argument(
        "--url", metavar="url", default=None,
        help="URL to planned hosting location of rendered JPEG pyramid",
    )
    parser.add_argument('--force', help='Overwrite output', action='store_true')
    args = parser.parse_args()

    ome_tiff = args.ome_tiff
    author_json = args.author_json
    output_dir = args.output_dir
    root_url = args.url
    force = args.force

    main(ome_tiff, author_json, output_dir, root_url, force)
