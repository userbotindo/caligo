FROM adekmaulana/caligo:latest

RUN apk update
VOLUME /home/caligo

# Set runtime settings
USER caligo
WORKDIR /home/caligo
CMD ["bash", "bot"]
