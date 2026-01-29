
data = "E-1,role-we,phone-fjdh,E2-hds,role-dgf,phone-68,email-wqe@gmail.com"
parts = data.split(",")

employees = []
current_emp = None

for part in parts:
    token = part.strip()
    if not token:
        continue
    
    lower = token.lower()
    
    if lower.startswith("role-"):
        if current_emp:
            current_emp["role"] = token[5:].strip() # Remove "role-"
    elif lower.startswith("phone-"):
        if current_emp:
            current_emp["phone"] = token[6:].strip() # Remove "phone-"
    elif lower.startswith("email-"):
        if current_emp:
            current_emp["email"] = token[6:].strip() # Remove "email-"
    else:
        # It's a Name
        if current_emp:
            employees.append(current_emp)
        current_emp = {
            "name": token,
            "role": "",
            "phone": "",
            "email": ""
        }

if current_emp:
    employees.append(current_emp)

import json
print(json.dumps(employees, indent=2))
