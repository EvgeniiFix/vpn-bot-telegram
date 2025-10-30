Telegram bot for selling VPN configurations with an integrated admin panel and payment system.

 Functionality
Selling VPN configurations

Integration with payment systems

Admin panel for management

Statistics and analytics

User and tariff management

Installation and configuration
Repository cloning:

bash
git clone https://github.com/ваш-username/vpn-bot-telegram.git
cd vpn-bot-telegram
Installing dependencies:

bash
pip install -r requirements.txt
Configuring the configuration:

Create a config.py file based on config.example.py

Specify the bot token and database settings

Configure the payment systems

Running the bot:

bash
python main.py
Project Structure:

vpn-bot-telegram/
main.py
requirements.txt
README.md

app/
init.py
handlers.py
admin_panel.py
database.py
payments.py
keyboards.py
update_db.py

Description of modules
main.py - main file for starting the bot
app/handlers.py - message and command handlers
app/admin_panel.py - admin panel functions
app/database.py - database handling
app/payments.py - payment processing
app/keyboards.py - interface keyboards
app/update_db.py - updating the database structure

Requirements
Python 3.8+

aiogram 2.x

aiosqlite

Other dependencies in requirements.txt

Configuration
Before starting, you need to configure the following:

Bot token from BotFather

Database settings

Payment system keys

Administrator rights

License
The project is distributed under the MIT license.
