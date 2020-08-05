FROM ubuntu:18.04

RUN apt-get update && apt-get install -y python3 python3-pip sudo


RUN useradd -m nandan

RUN chown -R nandan:nandan /home/nandan/

COPY --chown=nandan . /home/nandan/app/

#switch user
USER nandan

RUN cd /home/nandan/app/ && pip3 install -r requirements.txt

WORKDIR /home/nandan/app
