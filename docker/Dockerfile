FROM ubuntu:20.04

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3.11 \
    python3-pip \
    openslide-tools \
    python3-openslide

COPY minerva_story.sh /usr/local/bin/minerva_story.sh
COPY save_exhibit_pyramid.py /usr/local/bin/save_exhibit_pyramid.py
COPY index.html /usr/local/bin/index.html

WORKDIR /tmp
COPY requirements.txt /tmp
ENV CRYPTOGRAPHY_DONT_BUILD_RUST=1
RUN pip3 install --upgrade setuptools
RUN pip3 install -r /tmp/requirements.txt

USER root
RUN /bin/bash -c 'chmod +x /usr/local/bin/minerva_story.sh'
CMD [ "/bin/sh", "/usr/local/bin/minerva_story.sh" ]
