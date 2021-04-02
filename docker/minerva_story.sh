#!/bin/bash

IMAGE_S3_URL="s3://${DIR_NAME}/${INPUT_TIFF}"
STORY_S3_URL="s3://${DIR_NAME}/${INPUT_JSON}"
SUFFIX=".story.json"
OUTPUT_DIR="${INPUT_JSON%%$SUFFIX}"

error_exit () {
  echo "${BASENAME} - ${1}" >&2
  exit 1
}

# check aws cli program is available
which aws >/dev/null 2>&1 || error_exit "Unable to find AWS CLI executable."

aws s3 cp "${IMAGE_S3_URL}" "/data/${INPUT_TIFF}" || error_exit "Failed to download input ome-tiff file."
aws s3 cp "${STORY_S3_URL}" "/data/${INPUT_JSON}" || error_exit "Failed to download author json file."

cd /data

echo "Running rendering script save_exhibit_pyramid.py"
python3 /usr/local/bin/save_exhibit_pyramid.py "${INPUT_TIFF}" "${INPUT_JSON}" "${OUTPUT_DIR}" || error_exit "Failed to run save_exhibit_pyramid.py."

echo "Uploading jpeg pyramid and exhibit file to S3"
aws s3 cp "${OUTPUT_DIR}/" "s3://${DIR_NAME}/${OUTPUT_DIR}" --recursive --acl bucket-owner-full-control || error_exit "Failed to upload output folder to S3."

echo "Uploading index.html to S3"
aws s3 cp /usr/local/bin/index.html "s3://${DIR_NAME}/${OUTPUT_DIR}/index.html" --acl bucket-owner-full-control || error_exit "Failed to upload index.html to S3."

#clean up TIFF image and output directory
rm "${INPUT_TIFF}"
rm -r "${OUTPUT_DIR}/"
