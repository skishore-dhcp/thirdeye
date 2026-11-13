# ThirdEye

ThirdEye is a brand identity governance platform. An organization writes its brand guidelines once, and ThirdEye checks text, PDFs and images against them, fixes what it can, and sends the result through an approval step before it is used.

- Repository: https://github.com/skishore-dhcp/thirdeye

## Contents

1. [What ThirdEye does](#what-thirdeye-does)
2. [Using ThirdEye](#using-thirdeye)
3. [Limits](#limits)
4. [Running ThirdEye on your computer](#running-thirdeye-on-your-computer)
5. [Environment variables](#environment-variables)
6. [Project layout](#project-layout)
7. [Troubleshooting](#troubleshooting)

## What ThirdEye does

- Checks text, PDFs and images against an organization's guidelines.
- Supports three kinds of rule: words that must not be used, phrases that must be included, and tone / style rules.
- Checks the brand colours and logo in PDFs and images.
- Lists every issue with a suggested fix, and produces corrected text, an edited PDF where possible, and a PDF report.
- Routes content through an approval workflow with remarks.
- Keeps a Cumulative Organization Report, a full history, and insights on issues that keep coming back.
- Keeps every organization's data separate from every other organization's.

## Using ThirdEye

### Demo Mode

The quickest way to try ThirdEye. The first page offers three buttons: Try as Admin, Try as Reviewer and Try as Member. Each logs you in to the demo organization without typing anything.

You can also log in by hand with organization ID 1, the password demo, and one of these usernames:

- Admin: demo-admin
- Reviewer: demo123
- Member: demo-member

Reviewers and the Admin see a Reset demo data button on the dashboard, which restores the sample rules and brand colours.

### Creating an organization

1. On the login page, choose Create an organization.
2. Enter the organization's name, your username and a password.
3. You become the organization's Admin. ThirdEye shows your organization ID; share it with your team, because everyone needs it to log in.

A new organization starts with a few sample rules, which you can delete.

### Logging in

Logging in needs three things: the organization ID, your username and your password. Five wrong passwords lock that username for five minutes.

### Roles

Each organization has one Admin and any number of Reviewers and Members. In the app, the Reviewer role is labelled Authorized.

Members can:

- check content and download approved results;
- view the guidelines;
- view and download the Organization Report;
- download their own full history;
- receive alerts.

Reviewers can do everything a Member can, and also:

- add or delete guidelines, brand colours and the logo;
- approve or reject requests, with a remark;
- download the whole organization's history.

The Admin can do everything a Reviewer can, and also:

- add, remove, promote and demote members;
- send a message to everyone;
- delete the organization.

### The dashboard

After logging in you land on the dashboard. Choose your operation has a card for each main page. Below it, Insights on Repeated Issues lists issues that keep appearing.

The three-line button at the top right opens the menu, which holds your organization details, Alerts, Profile, Organization report, Documentation and Tutorial. The tutorial runs on your first login and can be replayed from the menu at any time.

### Setting guidelines

Open Add Guidelines. Members can view this page but cannot change it.

Rules. Pick a rule type, type the text, and choose Add. The three rule types are:

- Must not use: flags a word or phrase. If you give a replacement, ThirdEye swaps it in. With no replacement, the word becomes [removed] and the issue is marked for manual editing.
- Must include: flags content that is missing the phrase, and adds it.
- Tone / Style: describes how the content should sound, for example "Friendly and professional, no slang".

ThirdEye refuses a rule that would contradict another one, such as a replacement word that is itself banned.

Brand colours and logo. Add up to five colours as hex codes, choose how strict the colour match should be (Strict, Normal or Loose), and upload the logo as a PNG. Choose Save Guidelines.

### Checking content

Open Check Content and choose one of three tabs:

- Type or Paste Text: checks words, required phrases and tone.
- Upload PDF: checks words, required phrases, tone, colours and logo. Scanned PDFs are read with OCR.
- Upload Image: takes a PNG, JPG or WebP. The text is read with OCR, then words, required phrases, tone, colours and logo are checked.

Choose Check Content. The result lists each issue with the rule it broke, the text involved and a suggested fix.

- Items tagged Manual editing needed cannot be fixed automatically, and say what to do.
- Not fully checked means part of the check could not run, for example a tone rule when no Gemini key is set, or an image whose text was hard to read.
- Black, white and grey are never flagged as off-brand colours, and a colour must cover at least 5% of a page to be judged.

Then choose Approve or Reject:

- A Member's approval sends the content to the Reviewers as a request.
- A Reviewer or the Admin approves their own content directly.

A result that is neither approved nor rejected expires after 60 minutes.

### What you can download

After approval, a Download button appears. What you get depends on what you checked:

- Text: corrected_text.txt.
- PDF: a zip with corrected_text.txt, report.pdf, and corrected.pdf when there is something to change in it.
- Image: a zip with corrected_text.txt and report.pdf.

Your original file is never changed. ThirdEye does not edit images, because rewriting text inside a picture cannot be done reliably. Required phrases that are missing from a PDF are listed on a new last page for you to place.

### Approval requests

Open Approval Requests.

- Reviewers and the Admin see pending requests with their issues. Each has a Remark box beside Approve and Reject. A remark is required to reject, optional to approve, limited to 300 characters, and cannot be edited afterwards.
- Members see their own requests and their status.

History lists the last 15 decided requests. When a remark exists, View remark shows it along with who approved or rejected.

Download entire history (PDF) gives every check on record: the whole organization's for Reviewers and the Admin, and only your own for Members.

### Organization Report

Open Organization Report. It is read-only and available to every role. It shows:

- users by role;
- total checks, approvals, rejections, pending requests and issues found;
- approvals versus rejections;
- most used content types;
- most common issues;
- most revised content types;
- checks per day over the last 30 days.

Download PDF saves the same report as a file. The report shows organization-wide totals only, never one person's numbers.

### Alerts

Open the menu and choose Alerts. You are told when:

- your request is approved or rejected, with the remark;
- your role is changed;
- the Admin sends a message to everyone;
- you create a new organization (a welcome message).

### Profile

Open the menu and choose Profile. It shows your username, role and organization, your own counts (content checked, approved, rejected, pending), and a form to change your password. The shared demo accounts cannot change their password.

### Member management (Admin only)

Open Member Management to:

- add a member with a username and password;
- promote a Member to Reviewer, or demote a Reviewer to Member;
- remove a member, which also removes their requests;
- send a message of up to 300 characters to everyone.

The Admin cannot be demoted or removed.

### Deleting an organization (Admin only)

At the bottom of the menu, choose Delete organization, read the warning, and enter your password to confirm. This permanently removes every account and all data of the organization. The demo organization cannot be deleted.

## Limits

Content

- Typed or pasted text: 5,000 characters.
- PDF: 10 MB and 30 pages.
- Image: 10 MB; PNG, JPG or WebP.
- Colour and logo checks on a PDF: first 5 pages.

Guidelines

- Rule text: 200 characters.
- Brand colours: 5.
- Logo: PNG, 2 MB.

Accounts

- Username: 3 to 30 characters, using letters, digits, full stops, underscores and hyphens.
- Password: at least 6 characters.
- Organization name: 2 to 60 characters.

Messages

- Remark: 300 characters.
- Message to everyone: 300 characters.

What is kept

- Requests with their files: the last 15 decided requests per organization.
- An undecided result: expires after 60 minutes.
- Alerts: the newest 50 per user, with 10 shown.
- Full-history PDF: the newest 10,000 entries.

## Running ThirdEye on your computer

### What you need

- Python 3.13 or newer.
- Git.
- Tesseract OCR, the program that reads text in images and scanned PDFs. Text and ordinary PDFs work without it.
  - Windows: install it from the UB Mannheim Tesseract page and add its folder to your PATH.
  - macOS: brew install tesseract
  - Ubuntu or Debian: sudo apt install tesseract-ocr
- A Gemini API key (optional). It is needed only for Tone / Style rules. Create one in Google AI Studio.

You do not need to install a database. The steps below store everything in a file on your computer.

### 1. Get the code

```bash
git clone https://github.com/skishore-dhcp/thirdeye.git
cd thirdeye
```

### 2. Create a virtual environment and install the packages

macOS or Linux:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Windows:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Create the .env file

In the project folder, next to app.py, create a file named .env with this content:

```
DATABASE_URL=sqlite:///thirdeye.db
SECRET_KEY=replace-with-a-long-random-string
GEMINI_API_KEY=
DEMO_MODE=1
```

- DATABASE_URL is required. ThirdEye will not start without it. The value above stores everything in a file inside an instance folder.
- SECRET_KEY should be a long random string. To make one, run this command and paste the result:

  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
- GEMINI_API_KEY can stay empty. Paste your key after the = to turn on Tone / Style rules.
- DEMO_MODE=1 keeps the demo accounts and the one-click demo logins.

The .env file is listed in .gitignore. Never commit it, because it holds your keys.

### 4. Start ThirdEye

```bash
python app.py
```

Open http://127.0.0.1:5000 in your browser. On the first start ThirdEye creates its tables, the demo organization and the demo accounts by itself.

To stop it, press Ctrl+C in the terminal. To start again later, activate the virtual environment (step 2, second line) and run python app.py.

### Using PostgreSQL instead of a file

If you would rather use a PostgreSQL database, write its address in .env in this form:

```
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/DATABASE
```

The address must start with postgresql+psycopg2://. An address starting with postgresql:// stops ThirdEye with No module named 'psycopg'.

## Environment variables

All of these go in the .env file.

- DATABASE_URL (required): the database address. See step 3.
- SECRET_KEY (recommended): signs login sessions. Without it, a random key is made on each start and everyone is logged out whenever ThirdEye restarts.
- GEMINI_API_KEY (optional, empty by default): enables Tone / Style rules. Without it those rules are not checked and results say "Not fully checked".
- GEMINI_MODEL (optional, default gemini-3.1-flash-lite): which Gemini model to use.
- DEMO_MODE (optional, default 1, meaning on): set to 0 to remove the demo page and lock the demo accounts.
- DEMO_ADMIN_USERNAME, DEMO_USERNAME, DEMO_MEMBER_USERNAME (optional, defaults demo-admin, demo123, demo-member): usernames of the demo accounts.
- DEMO_ADMIN_PASSWORD, DEMO_PASSWORD, DEMO_MEMBER_PASSWORD (optional, default demo): passwords of the demo accounts.

Other settings, such as the size limits and the documentation link (DOCS_URL), are in config.py.

## Project layout

- app.py: the web app, with its pages, logins, roles, approvals and database setup.
- checks.py: the checking pipeline, with rules, PDF editing, OCR, and colour and logo checks.
- llm.py: the Gemini call for tone rules and phrase placement.
- models.py: the database tables.
- stats.py: the permanent check log and the numbers behind reports.
- reports.py: charts and the three PDFs.
- insights.py: repeated-issue insights.
- config.py: settings and limits.
- templates/: the HTML pages.
- static/: the stylesheet, script and images.
- requirements.txt: the Python packages.

## Troubleshooting

- DATABASE_URL is not set on start. The .env file is missing, misnamed or in the wrong folder. It must be named exactly .env and sit next to app.py.
- No module named 'psycopg'. The database address starts with postgresql://. Change it to postgresql+psycopg2://.
- Image or scanned PDF checks fail. Tesseract is not installed, or is not on your PATH.
- Tone rules show "Not fully checked". GEMINI_API_KEY is empty or invalid.
- Everyone is logged out after a restart. SECRET_KEY is not set.
- Forgot the organization ID. It is shown in the menu when logged in. The Admin can share it.
- Want to start over. Stop ThirdEye and delete the instance folder. The next start creates a fresh database.
