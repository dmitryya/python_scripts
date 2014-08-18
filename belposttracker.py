#!/usr/bin/env python2
# coding: utf8
#
# Copyright (C) 2010 Dmitry Yatsushkevich <dmitry.yatsushkevich@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

import urllib3
from bs4 import BeautifulSoup
from datetime import date
from prettytable import PrettyTable
from argparse import ArgumentParser
from argparse import FileType
import re
from sys import stdout
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import traceback
import sys

BELPOST_URL = 'http://search.belpost.by/ajax/search/'


class BelPostGetter():

    def __init__(self, retry=5):
        self.http = urllib3.PoolManager()
        self.tables = []
        self.retry = retry

    def _get_internal(self, values):
        r = self.http.request('GET', BELPOST_URL, values)
        soup = BeautifulSoup(r.data.decode('UTF-8'))
        tables = []

        for table in soup.find_all("table", attrs={"class": "tbl"}):
            # The first tr contains the field names.
            headings = [th.get_text() for th in
                        table.find("tr").find_all("td", class_='theader')]

            datasets = []
            for row in table.find_all("tr")[1:]:
                datasets.append([td.get_text() for td in row.find_all("td")])
            if datasets:
                tables.append({'header': headings, 'data': datasets})

        return tables

    def get(self, track):
        values = {'internal': '2', 'item': track}
        self.tables = self._get_internal(values)
        while self.tables == [] and self.retry > 0:
            self.tables = self._get_internal(values)
            self.retry -= 1

        return self.tables


def PlainTextTableReport(track, data):
    report = 'Track: %s, Desc: %s, Details: %s\n' % (
        track['track'], track['desc'], track['extra'])
    for t in data:
        tab = PrettyTable(t['header'])
        tab.padding_width = 1
        tab.align = 'l'

        # add rows
        for row in t['data']:
            tab.add_row(row)

        report += str(tab) + '\n'

    report += "\n*********************************************************\n\n"

    return report


def PlainTextReport(track, data):
    report = 'Track: %s, Desc: %s, Details: %s\n' % (
        track['track'], track['desc'], track['extra'])
    for t in data:
        # add rows
        for row in t['data']:
            line = ' - '.join(row)
            report += line + '\n'

        report += '\n'
    return report.encode('UTF-8')


def InParser(file):
    result = []
    regex = re.compile(
        "(?P<track>.*?)\s+-\s+(?P<desc>.*?)\s+-\s+(?P<extra>.*?)$")
    for line in file:
        if line[0] != '#':
            match = regex.match(line)
            if match:
                result.append({
                    'track': match.group("track"),
                    'extra': match.group("extra"),
                    'desc': match.group("desc")
                })
    return result


def send_mail(to_address, from_address, server, port, user, passwd, tls, data, data_type):
    try:
        msg = MIMEText(data, data_type)
        msg['Subject'] = "Track status %s" % date.today().strftime("%d/%m/%y")
        msg['From'] = from_address
        msg['To'] = to_address
        msg.set_charset('UTF-8')

        s = smtplib.SMTP(server, port)
        if tls:
            s.starttls()
        if user != '':
            s.login(user, passwd)
        s.sendmail(from_address, to_address, msg.as_string())
    except smtplib.SMTPException, e:
        print '[smtplib] SMTP error: ', str(e)
    except smtplib.socket.error, e:
        print '[smtplib.socket] error: ', e
    except Exception as e:
        traceback.print_exc(file=sys.stdout)


def main():

    try:
        reports = {'table': PlainTextTableReport,
                   'plain': PlainTextReport}

        parser = ArgumentParser()
        parser.add_argument("-l", "--list", nargs='?', required=True, dest="tracks",
                            type=FileType('rt'), help="Plane text file with parcel tracks")
        parser.add_argument("-f", "--format", nargs='?', required=True, dest="format", choices=['table', 'plain'],
                            type=str, help="Output report format")

        out_group = parser.add_mutually_exclusive_group()
        out_group.add_argument("-o", "--output", nargs='?', dest="output",
                            type=FileType('wt'), help="File name for report")
        out_group.add_argument("-s", "--silent", dest="silent", action='store_true', default=False,
                            help="Enable silent mode.")

        email_group = parser.add_argument_group('EMAIL Notification')
        email_group.add_argument("--to", nargs='?', dest="to_address", metavar='ADDRESS', type=str,
                                 help="Specify the primary recipient of the emails generated.")
        email_group.add_argument("--from", nargs='?', dest="from_address", metavar='ADDRESS', type=str, default='',
                                 help="Specify the sender of the emails.")
        email_group.add_argument("--smtp-user", nargs='?', dest="smtp_user", metavar='USER', type=str, default='',
                                 help="Username for SMTP-AUTH.")
        email_group.add_argument("--smtp-pass", nargs='?', dest="smtp_pass", metavar='PASSWORD', type=str,
                                 help="Password for SMTP-AUTH.")
        email_group.add_argument("--smtp-server", nargs='?', dest="smtp_server", metavar='HOST', default="127.0.0.1",
                                 type=str, help="Specifies the outgoing SMTP server to use. Default 127.0.0.1")
        email_group.add_argument("--smtp-port", nargs='?', dest="smtp_port", metavar='PORT', type=str,
                                 help="Specifies a port different from the default port(25).")
        email_group.add_argument("--smtp-tls", dest="smtp_tls", action='store_true',  default=False,
                                 help="Specify the TLS encryption to use.")
        options = parser.parse_args()

        file = stdout

        if options.output is not None:
            file = options.output
        elif options.silent:
            file = None

        tracks = InParser(options.tracks)
        report = reports[options.format]
        getter = BelPostGetter()
        out = ''
        for t in tracks:
            res = report(t, getter.get(t['track']))
            out += res
            if file is not None:
                file.write(res)
                file.flush()

        if options.to_address is not None:
            send_mail(options.to_address, options.from_address, options.smtp_server, options.smtp_port,
                      options.smtp_user, options.smtp_pass, options.smtp_tls, out, 'plain')

        if file is not None:
            file.close()

    except (KeyboardInterrupt, SystemExit):
        print "Stopped"

if __name__ == "__main__":
    main()
