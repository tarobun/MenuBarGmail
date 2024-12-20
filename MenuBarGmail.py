#!/usr/bin/env python
"""
Gmail notification in Menu bar.

requirement: rumps (https://github.com/jaredks/rumps),
             httplib2, oauth2client, google-api-python-client
Worked with python 3.9
"""

import os
import sys
import re
import argparse
import base64
import dateutil.parser
import dateutil.tz
import httplib2
import rumps
import socket
import signal
import urllib
import webbrowser
from email.mime.text import MIMEText
from oauth2client.file import Storage
from oauth2client.tools import run_flow, argparser
from oauth2client.client import OAuth2WebServerFlow
from apiclient.discovery import build
from apiclient import errors

__prog__ = os.path.basename(__file__)
__description__ = __doc__
__author__ = "rcmdnk"
__copyright__ = "Copyright (c) 2015 rcmdnk"
__credits__ = ["rcmdnk"]
__license__ = "MIT"
__version__ = "v0.2.0"
__date__ = "01/Jun/2022"
__maintainer__ = "rcmdnk"
__email__ = "rcmdnk@gmail.com"
__status__ = "Prototype"

DEBUG = True
MAILS_MAX_GET = 10
MAILS_MAX_SHOW = 10
AUTHENTICATION_FILE = os.environ["HOME"] + "/.menubargmail_oauth"
SETTING_FILE = os.environ["HOME"] + "/.menubargmail_settings"
PLIST_FILE = os.environ["HOME"] + "/Library/LaunchAgents/menubargmail.plist"
GOOGLE_CLIENT_ID = (
    "401979756927-453hrgvmgjik9tqqq744s6pg7762hfel.apps.googleusercontent.com"
)
GOOGLE_CLIENT_SECRET = "sso7NdujDxkT92bxK2u-RPGi"
MENU_BAR_ICON = ["MenuBarGmailMenuBarIcon.png", "MenuBarGmailMenuBarIconForDark.png"]

MENU_INBOX = "Inbox"
MENU_CHECK_NOW = "Check now"
MENU_RECONNECT = "Reconnect"
MENU_UNREAD_MESSAGES = "Unread messages"
MENU_SET_CHECKING_INTERVAL = "Set checking interval"
MENU_SET_LABELS = "Set labels"
MENU_SET_FILTER = "Set filter"
MENU_MENUBAR_ICON = "Menubar icon for dark"
MENU_MAIL_NOTIFICATION = "Mail notification"
MENU_START_AT_LOGIN = "Start at login"
MENU_UNINSTALL = "Uninstall"
MENU_ABOUT = "About"


class MenuBarGmail(rumps.App):
    def __init__(self, autostart=True):
        # Set default values
        self.debug_mode = DEBUG
        rumps.debug_mode(self.debug_mode)
        self.mails_max_get = MAILS_MAX_GET
        self.mails_max_show = MAILS_MAX_SHOW
        self.authentication_file = AUTHENTICATION_FILE
        self.setting_file = SETTING_FILE
        self.plist_file = PLIST_FILE
        self.google_client_id = GOOGLE_CLIENT_ID
        self.google_client_secret = GOOGLE_CLIENT_SECRET
        self.menu_bar_icon = MENU_BAR_ICON

        # Read settings
        self.settings = {}
        self.read_settings()

        # Application setup
        super(MenuBarGmail, self).__init__(
            type(self).__name__, title=None, icon=self.menubar_icon()
        )

        # Other class variables
        self.address = ""
        self.address = ""
        self.messages = {}
        self.message_contents = {}
        self.service = None
        self.is_first = True

        # Setup menu
        self.menu = [
            MENU_INBOX,
            MENU_CHECK_NOW,
            MENU_RECONNECT,
            MENU_UNREAD_MESSAGES,
            None,
            MENU_SET_CHECKING_INTERVAL,
            MENU_SET_LABELS,
            MENU_SET_FILTER,
            None,
            MENU_MENUBAR_ICON,
            MENU_MAIL_NOTIFICATION,
            MENU_START_AT_LOGIN,
            None,
            MENU_UNINSTALL,
            None,
            MENU_ABOUT,
        ]

        self.menu[MENU_MENUBAR_ICON].state = self.settings_state("menubariconfordark")
        self.menu[MENU_MAIL_NOTIFICATION].state = self.settings_state("notification")
        self.menu[MENU_START_AT_LOGIN].state = self.settings_state("startatlogin")

        # Set and start get_messages
        self.get_messages_timer = rumps.Timer(
            self.get_messages_wrapper, int(self.settings_value("interval", 60))
        )
        if autostart:
            self.start()

    def menubar_icon(self):
        icon_index = int(self.settings_value("menubariconfordark", 1))
        return self.menu_bar_icon[icon_index]

    def settings_value(self, name, default_value):
        return self.settings[name] if name in self.settings else default_value

    def settings_state(self, name):
        return True if self.settings_value(name, "") == "1" else False

    @rumps.clicked(MENU_INBOX)
    def account(self, sender):
        self.open_gmail()
        rumps.Timer(self.get_messages, 10).start()

    @rumps.clicked(MENU_CHECK_NOW)
    def check_now(self, sender):
        self.get_messages()

    @rumps.clicked(MENU_RECONNECT)
    def reconnect(self, sender):
        self.build_service(True)
        self.restart()

    @rumps.clicked(MENU_SET_CHECKING_INTERVAL)
    def set_interval(self, sender):
        # Need to stop timer job, otherwise interval can not be changed.
        self.stop()
        response = rumps.Window(
            "Set checking interval (s)",
            default_text=str(self.get_messages_timer.interval),
            dimensions=(100, 20),
        ).run()
        if response.clicked:
            self.get_messages_timer.interval = int(response.text)
            self.settings["interval"] = response.text
            self.write_settings()
            self.restart()

    @rumps.clicked(MENU_SET_LABELS)
    def set_labels(self, sender):
        response = rumps.Window(
            "Set labels (comma-separeted list).\n"
            'If "labels" is empty and filter is not set, INBOX is checked.',
            default_text=self.settings_value("labels", ""),
            dimensions=(400, 20),
        ).run()
        if response.clicked:
            self.settings["labels"] = response.text.upper()
            self.write_settings()
            self.restart()

    @rumps.clicked(MENU_SET_FILTER)
    def set_filter(self, sender):
        response = rumps.Window(
            "Set filter.\n"
            'e.g. "newer_than:1w" for mails within a week\n'
            "ref: https://support.google.com/mail/answer/7190",
            default_text=self.settings_value("filter", ""),
            dimensions=(400, 20),
        ).run()
        if response.clicked:
            self.settings["filter"] = response.text.upper()
            self.write_settings()
            self.restart()

    @rumps.clicked(MENU_MENUBAR_ICON)
    def set_filter(self, sender):
        sender.state = not sender.state
        self.settings["menubariconfordark"] = str(sender.state)
        self.icon = self.menubar_icon()
        self.write_settings()

    @rumps.clicked(MENU_MAIL_NOTIFICATION)
    def mail_notification(self, sender):
        sender.state = not sender.state
        self.settings["notification"] = str(sender.state)
        self.write_settings()

    @rumps.clicked(MENU_START_AT_LOGIN)
    def set_startup(self, sender):
        sender.state = not sender.state
        if sender.state == 0:
            if os.path.exists(self.plist_file):
                os.system("launchctl unload %s" % self.plist_file)
                os.remove(self.plist_file)
        else:
            plist = (
                '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN"'''
                """ "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
        <key>Label</key>
        <string>menubargmail</string>
        <key>ProgramArguments</key>
        <array>
            <string>"""
                + self.get_exe()
                + """</string>
        </array>
        <key>RunAtLoad</key>
        <true/>
</dict>
</plist>"""
            )
            with open(self.plist_file, "w") as f:
                f.write(plist)

        self.settings["startatlogin"] = str(sender.state)
        self.write_settings()

    @rumps.clicked(MENU_UNINSTALL)
    def uninstall(self, sender):
        ret = rumps.alert(
            "Do you want to uninstall MenuBarGmail?", ok="OK", cancel="Cancel"
        )
        if ret == 1:
            self.remove_me()

    @rumps.clicked(MENU_ABOUT)
    def about(self, sender):
        rumps.alert(
            title="%s" % __prog__,
            message="Gmail notification in Menu bar.\n"
            + "Version %s\n" % __version__
            + "%s" % __copyright__,
        )

    def error_check(func):
        def wrapper(*args, **kargs):
            try:
                func(*args, **kargs)
            except errors.HttpError as e:
                print(f"[ERROR] {sys._getframe().f_code.co_name}: {e}")
                args[0].service = None
            except (httplib2.ServerNotFoundError, socket.error) as e:
                print(f"[ERROR] {sys._getframe().f_code.co_name}: Maybe offline, {e}")
                args[0].service = None
            except Exception as e:
                if len(e.args) > 0 and "timeout" in e.args[0]:
                    err_msg = e.args[0]
                else:
                    err_msg = f"Unexpected, {sys.exc_info()[0]}"
                print(f"[ERROR] {sys._getframe().f_code.co_name}: {err_msg}")
                args[0].service = None

        return wrapper

    def get_messages_wrapper(self, sender):
        self.get_messages()

    @rumps.notifications
    def notification_center(self, info):
        self.show_mail("INBOX", info.data)

    @error_check
    def get_messages(self, commandline=False):
        # Set labels
        labels = []
        if "labels" in self.settings and self.settings["labels"] != "":
            for l in self.settings["labels"].split(","):
                labels.append(l.strip())
        elif "filter" not in self.settings or self.settings["filter"].strip() == "":
            labels.append("INBOX")

        is_inbox_only = True if "INBOX" in labels and len(labels) == 1 else False

        if not is_inbox_only:
            # Get label ids
            all_labels = self.timeout_execute(self.get_all_labels().list(userId="me"))
            label_name_id = {
                x["name"].upper().replace("/", "-"): x["id"]
                for x in all_labels["labels"]
            }
        else:
            label_name_id = {"INBOX": "INBOX", "None": None}

        labels = [x for x in labels if x.replace("/", "-") in label_name_id]
        if len(labels) == 0:
            labels.append("None")

        # Get message ids
        query = "label:unread " + self.settings_value("filter", "")
        ids = {}
        is_new = False
        for l in labels:
            response = self.timeout_execute(
                self.get_all_messages().list(
                    userId="me", labelIds=label_name_id[l.replace("/", "-")], q=query
                )
            )

            ids[l] = []
            if "messages" in response:
                ids[l].extend([x["id"] for x in response["messages"]])

            while "nextPageToken" in response:
                page_token = response["nextPageToken"]
                response = self.timeout_execute(
                    self.get_all_messages().list(
                        userId="me",
                        labelIds=label_name_id[l.replace("/", "-")],
                        q=query,
                        pageToken=page_token,
                    )
                )
                ids[l].extend([x["id"] for x in response["messages"]])

            if l not in self.messages:
                self.messages[l] = []
            if ids[l] != self.messages[l]:
                is_new = True

            # Remove read messages' id
            self.messages[l] = ids[l]

        removed = [x for x in self.messages if x not in labels]
        if len(removed) > 0:
            is_new = True
            for l in removed:
                del self.messages[l]

        # No change
        if not is_new:
            # No new message
            return

        # Check total number of messages
        # Remove duplication in different labels
        all_ids = list({id for l in labels for id in ids.get(l, [])})
        all_ids_count = len(all_ids)

        self.message_contents = {
            k: v for k, v in self.message_contents.items() if k in all_ids
        }

        # Set menu's title
        um_menu = self.menu[MENU_UNREAD_MESSAGES]
        um_menu.title = "Unread messages: %d" % all_ids_count
        um_menu.set_callback(None if all_ids_count == 0 else self.get_messages)

        # Set menubar icon's title
        self.title = "" if all_ids_count == 0 else "%d" % all_ids_count

        # Reset menu bar icon after title is put, to adjust the width.
        self.icon = self.menubar_icon()

        # Get message contents
        n_get = 0
        for i in all_ids:
            if i in self.message_contents and "Subject" in self.message_contents[i]:
                continue

            is_new = True if i not in self.message_contents else False
            self.message_contents[i] = {}
            if n_get >= self.mails_max_get:
                continue

            n_get += 1
            message = self.timeout_execute(
                self.get_all_messages().get(userId="me", id=i)
            )

            for k in ["labelIds", "snippet", "threadId"]:
                self.message_contents[i][k] = message[k]

            for x in message["payload"]["headers"]:
                val = x["value"]
                match x["name"]:
                    case "Subject":
                        self.message_contents[i]["Subject"] = val
                    case "Date":
                        d = dateutil.parser.parse(val.split(", ")[1].split(" +")[0])
                        utc_date = d.replace(tzinfo=dateutil.tz.tzutc())
                        local_date = utc_date.astimezone(dateutil.tz.tzlocal())
                        self.message_contents[i]["Date"] = local_date.strftime(
                            "%d %b %Y %H:%M"
                        )
                    case "From":
                        self.message_contents[i]["FromName"] = self.get_addr_name(val)
                        self.message_contents[i]["From"] = val
                    case [
                        "Subject" | "To" | "Cc" | "Bcc" | "In-Reply-To" | "References"
                    ]:
                        self.message_contents[i][x["name"]] = val

            for k in ["To", "Cc"]:
                if k not in self.message_contents[i]:
                    self.message_contents[i][k] = ""

            body = None
            if "parts" in message["payload"]:
                for p in message["payload"]["parts"]:
                    if "body" in p and "data" in p["body"]:
                        body = p["body"]["data"]
                        break
                if (
                    body is None
                    and "body" in message["payload"]
                    and "data" in message["payload"]["body"]
                ):
                    body = message["payload"]["body"]["data"]
                if body is not None:
                    self.message_contents[i]["body"] = base64.urlsafe_b64decode(
                        body.encode("UTF-8")
                    )

            if body is None:
                self.message_contents[i]["body"] = message["snippet"]

            # Popup notification
            notify = self.menu[MENU_MAIL_NOTIFICATION].state == 1
            if is_new and notify and not self.is_first:
                rumps.notification(
                    title="Mail from %s" % self.message_contents[i]["FromName"],
                    subtitle=self.message_contents[i]["Subject"],
                    message=self.message_contents[i]["snippet"],
                    data=i,
                )

        self.is_first = False

        # Get contents
        if um_menu._menu is not None:
            um_menu.clear()
        for l in labels:
            threadIds = []
            if len(labels) > 1:
                # Set each labels' menu
                um_menu.add(
                    rumps.MenuItem(l, callback=lambda x, y=l: self.open_gmail(y))
                )
                um_menu[l].title = "%s: %d" % (l, len(ids[l]))
            for i in sorted(
                [i for i in self.messages[l] if "Subject" in self.message_contents[i]],
                key=lambda x: self.message_contents[x]["Date"],
                reverse=True,
            ):
                v = self.message_contents[i]
                if v["threadId"] in threadIds:
                    continue
                threadIds.append(v["threadId"])
                title = "%s | %s | %s" % (v["Date"], v["FromName"], v["Subject"])
                title = title[0:80]
                m = um_menu[l] if len(labels) > 1 else um_menu
                if len(m) < self.mails_max_show:
                    m.add(
                        rumps.MenuItem(
                            l + str(i),
                            callback=lambda x, y=l, z=i: self.show_mail(y, z),
                        )
                    )
                    m[l + str(i)].title = title
                    m[l + str(i)].add(
                        rumps.MenuItem(
                            l + str(i) + "snippet",
                            callback=lambda x, y=l, z=i: self.show_mail(y, z),
                        )
                    )
                    m[l + str(i)][l + str(i) + "snippet"].title = v["snippet"]

        if commandline or self.debug_mode:
            print("")
            print("labels: %s" % self.settings_value("labels", ""))
            print("filter: %s" % self.settings_value("filter", ""))
            print("Total number of unread messages: %d\n" % len(all_ids))
            if len(labels) == 1:
                for i in um_menu.values():
                    print(i.title)
            else:
                for l in labels:
                    print("%d messages for %s" % (len(ids[l]), l))
                    for i in um_menu[l].values():
                        print(i.title)

    def read_settings(self):
        if not os.path.exists(self.setting_file):
            return
        with open(self.setting_file, "r") as f:
            for line in f:
                l = re.sub(r" *#.*", "", line).strip()
                if l == "":
                    continue
                l = l.split("=")
                if len(l) < 2:
                    continue
                if l[0] == "labels":
                    self.settings[l[0]] = l[1].upper()
                else:
                    self.settings[l[0]] = l[1]

    def write_settings(self):
        with open(self.setting_file, "w") as f:
            for k, v in self.settings.items():
                f.write("%s=%s\n" % (k, v))

    def build_service(self, rebuild=False):
        storage = Storage(os.path.expanduser(self.authentication_file))
        credentials = storage.get()

        if rebuild or credentials is None or credentials.invalid:
            credentials = self.authentication(storage)

        http = httplib2.Http()
        http = credentials.authorize(http)

        service = build("gmail", "v1", http=http)

        prof = self.timeout_execute(service.users().getProfile(userId="me"))
        self.address = prof["emailAddress"]
        self.menu[MENU_INBOX].title = "Inbox: %s" % self.address

        return service

    def get_service(self):
        if self.service is None:
            self.service = self.build_service()
        return self.service

    def get_all_messages(self):
        return self.get_service().users().messages()

    def get_all_drafts(self):
        return self.get_service().users().drafts()

    def get_all_labels(self):
        return self.get_service().users().labels()

    def authentication(self, storage):
        return run_flow(
            OAuth2WebServerFlow(
                client_id=self.google_client_id,
                client_secret=self.google_client_secret,
                scope=["https://www.googleapis.com/auth/gmail.modify"],
            ),
            storage,
            argparser.parse_args([]),
        )

    def open_gmail(self, label=""):
        url = "https://mail.google.com"
        if label != "":
            url += "/mail/u/0/#label/" + urllib.quote(label.encode("utf-8"))
        webbrowser.open(url)

    def show_mail(self, label, msg_id):
        # rumps.alert(title='From %s\n%s' % (sender, date),
        #             message=subject + '\n\n' + message)
        v = self.message_contents[msg_id]
        w = rumps.Window(
            message=v["Subject"] + "\n\n" + v["snippet"],
            title="From %s\n%s" % (v["From"], v["Date"]),
            dimensions=(0, 0),
            ok="Cancel",
            cancel="Open in browser",
        )
        w.add_button("Mark as read")
        w.add_button("Reply")
        response = w.run()
        if response.clicked == 0:
            self.open_gmail(label)
        elif response.clicked == 2:
            self.mark_as_read(msg_id)
        elif response.clicked == 3:
            self.reply(msg_id)

    def get_exe(self):
        exe = os.path.abspath(__file__)
        if exe.find("Contents/Resources/") != -1:
            name, ext = os.path.splitext(exe)
            if ext == ".py":
                exe = name
            exe = exe.replace("Resources", "MacOS")
        return exe

    def get_app(self):
        exe = self.get_exe()
        if exe.find("Contents/MacOS/") == -1:
            # Not in app
            return ""
        else:
            return os.path.dirname(exe).replace("/Contents/MacOS", "")

    def reset(self):
        if os.path.exists(self.plist_file):
            os.system("launchctl unload %s" % self.plist_file)
            os.remove(self.plist_file)

        app_support_path = "/Library/Application Support/MenuBarGmail"
        os.system("rm -f %s %s" % (self.authentication_file, self.setting_file))
        os.system('rm -rf "%s/%s"' % (os.environ["HOME"], app_support_path))

    def remove_me(self):
        self.reset()
        app = self.get_app()
        if app != "":
            os.system('rm -rf "%s"' % app)
        else:
            print("%s is not in App" % self.get_exe())

    def start(self):
        self.get_messages_timer.start()

    def stop(self):
        if self.get_messages_timer.is_alive():
            self.get_messages_timer.stop()

    def restart(self):
        self.stop()
        self.start()

    @error_check
    def remove_labels(self, msg_id, labels):
        if type(labels) == str:
            labels = [labels]
        msg_labels = {"addLabelIds": [], "removeLabelIds": labels}
        self.timeout_execute(
            self.get_all_messages().modify(userId="me", id=msg_id, body=msg_labels)
        )

    def mark_as_read(self, msg_id):
        self.remove_labels(msg_id, "UNREAD")
        self.get_messages()

    def get_addr_name(self, address):
        return re.sub(r" *<.*> *", "", address)

    def get_addr(self, address):
        try:
            return re.search(r"(?<=<).*(?=>)", address).group()
        except:
            return address

    @error_check
    def reply(self, msg_id):
        v = self.message_contents[msg_id]
        to = self.get_addr(v["From"])
        cc_tmp = []
        cc_tmp += v["To"].split(",") if v["To"] != "" else []
        cc_tmp += v["Cc"].split(",") if v["Cc"] != "" else []

        cc = []
        for a in cc_tmp:
            if a.lower() not in [to.lower(), self.address.lower()]:
                cc.append(self.get_addr(a))

        body = ""
        for l in v["body"].split("\n"):
            body += "> " + l + "\n"

        w = rumps.Window(
            "To: %s\n" % to + "Cc: %s\n" % ",".join(cc) + "From: %s\n" % self.address,
            default_text=body,
            dimensions=(500, 500),
            ok="Cancel",
            cancel="Send",
        )
        w.add_button("Save")
        response = w.run()

        if response.clicked == 1:
            pass
        elif response.clicked in [0, 2]:
            message = MIMEText(response.text)
            message["to"] = to
            message["cc"] = "".join(cc)
            message["from"] = self.address
            message["subject"] = "Re: " + v["Subject"]
            m = {"raw": base64.urlsafe_b64encode(message.as_string())}
            if response.clicked == 1:
                self.timeout_execute(self.get_all_messages().send(userId="me", body=m))
            elif response.clicked == 2:
                self.timeout_execute(
                    self.get_all_drafts().create(userId="me", body={"message": m})
                )

    def timeout_execute(self, obj, t=1):
        def handler(signum, frame):
            raise Exception("Over %d sec, timeout!" % (t))

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(t)
        ret = obj.execute()
        signal.alarm(0)
        return ret


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog=__prog__,
        formatter_class=argparse.RawTextHelpFormatter,
        description=__description__,
    )
    parser.add_argument(
        "-u",
        "--uninstall",
        action="store_true",
        dest="uninstall",
        default=False,
        help="Uninstall %s" % __prog__,
    )
    parser.add_argument(
        "-r",
        "--reset",
        action="store_true",
        dest="reset",
        default=False,
        help="Reset settings",
    )
    parser.add_argument(
        "-c",
        "--commandline",
        action="store_true",
        dest="commandline",
        default=False,
        help="Check mails once in command line",
    )
    args = parser.parse_args()
    app = MenuBarGmail(not (args.uninstall or args.reset or args.commandline))
    if args.uninstall:
        app.remove_me()
    elif args.reset:
        app.reset()
    elif args.commandline:
        app.get_messages(True)
    else:
        app.run()
