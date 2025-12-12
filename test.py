import imaplib

imap = imaplib.IMAP4_SSL("imap.gmail.com")
imap.login("ai.intern@cetl.in", "qxsmvqolhuprpkwh")
print("LOGIN OK")
