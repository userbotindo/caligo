<h1 align="center">Caligo</h1>

A SelfBot for Telegram made with Python using [Pyrogram](https://github.com/pyrogram/pyrogram) library. It's highly inspired from [pyrobud](https://github.com/kdrag0n/pyrobud) that writtens in [Telethon](https://github.com/LonamiWebs/Telethon) library.
It's the same but different, you know what i mean?
Caligo needs **Python 3.11** or newer to run.

## Compatibility

Caligo should work with all Linux-based operating systems.

This program tested partially on MacOs M1 and not officially support for windows.

## Installation

Caligo uses MongoDB Atlas for it database, you can get it free at <https://www.mongodb.com/> and save the uri for use on config and to generate your session.

Obviously you need git, and it should be already installed on major operating systems linux based.

### Local

First, clone this Git repository locally: `git clone https://github.com/adekmaulana/caligo`

After that, you can run `python3 -m pip install .` to install the bot along with the depencies.

Once it's installed, you can choose to invoke it using the `caligo` command, or run the bot in-place (which is described later in the Usage section). Running it in-place is recommended to allow for automatic updates via Git.

#### Error: Directory '.' is not installable. File 'setup.py' not found.

This common error is caused by an outdated version of pip. We use the Poetry package manager to make things easier to maintain, which works with pip through PEP-517. This is a relatively new standard, so a newer version of pip is necessary to make it work.

Upgrade to pip 19 to fix this issue: `pip3 install -U pip`

### Using Heroku

#### Config Gist
- Go to [gist.github.com](https://gist.github.com/)
- Create a new gist and make sure it's private/secret
- Copy the content of `sample_config.toml` and paste it to your gist
- Fill the coresponding _Name_ and _Value_
- Make sure you name the gist as `config.toml`
- Click **Create secret gist** and copy the link save for later use

#### Deploying
- Go to your [dashboard](https://dashboard.heroku.com/apps)
- Create an empty application then go to the app setting
- Scroll a bit until you find **Buildpacks** section
- Click **Add Buildpack** and choose **Python** and then click **Save Changes**
- Click **Add Buildpack** again and put this [repo](https://github.com/userbotindo/heroku-buildpack-caligo-helper) and then click **Save Changes**
- Scroll top a bit until you find **Reveal Config Vars** > Click it
    * Fill `CONFIG` with the link of your recently created gist
    * Fill `GITHUB_REPO` with your forked repo link
    * Fill `GITHUB_BRANCH` with your branch name
- Go to **Deploy** tab and connect your github account
- Choose your forked repo and then click **Deploy Branch**
- It should be finished around 1-2 minute(s)
- Go to **Resources** tab and turn on the worker

## Generating Session

### Heroku

Click more on your app page and the click **Run console** and run this command `python3 generate_session.py`.
Fill the `API_ID`, `API_HASH` and `MONGODB URI` when it asked and wait until it finished and your userbot is ready.

### Local

Just run the bot normally.

## Configuration

Copy `sample_config.toml` to `config.toml` and edit the settings as desired. Each and every setting is documented by the comments above it.

Obtain the _API ID_ and _API HASH_ from [Telegram's website](https://my.telegram.org/apps). **TREAT THESE SECRETS LIKE A PASSWORD!**

Obtain the DB_URI from [MongoDB](https://cloud.mongodb.com/). **TREAT THIS SECRETS LIKE A PASSWORD!**

Configuration must be complete before starting the bot for the first time for it to work properly.

## Usage

To start the bot, type `python3 main.py` or `python3 -m caligo` if you are running it in-place or use command corresponding to your chosen installation method above.

## Support

Feel free to join the official support group on Telegram for help or general discussion regarding the bot. You may also open an [issue](https://github.com/adekmaulana/caligo/issues) on GitHub for bugs, suggestions, or anything else relevant to the project.
