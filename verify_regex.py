import re

text = 'The email has been sent to varun.gupt@rmc.in with the subject "high" and body "hello".'
text2 = 'The email has been sent to foo@bar.com with subject: "Meeting" and body: "Hi there"'

# Regex from main.py
subj_regex = r"subject[:\s]+['\"`](.+?)['\"`]"
body_regex = r"body[:\s]+['\"`](.+?)['\"`]"

print(f"Testing text: {text}")
m_subj = re.search(subj_regex, text, re.IGNORECASE)
if m_subj:
    print(f"Subject Match: '{m_subj.group(1)}'")
else:
    print("Subject Match: NONE")

m_body = re.search(body_regex, text, re.IGNORECASE)
if m_body:
    print(f"Body Match: '{m_body.group(1)}'")
else:
    print("Body Match: NONE")

print(f"\nTesting text2: {text2}")
m_subj2 = re.search(subj_regex, text2, re.IGNORECASE)
if m_subj2:
    print(f"Subject Match: '{m_subj2.group(1)}'")
else:
    print("Subject Match: NONE")

m_body2 = re.search(body_regex, text2, re.IGNORECASE)
if m_body2:
    print(f"Body Match: '{m_body2.group(1)}'")
else:
    print("Body Match: NONE")
