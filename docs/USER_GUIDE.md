# Cicero user guide

Cicero makes a translated copy of a PowerPoint presentation using Google Cloud
Translation. The original file is only ever **read**; the translation is saved
as a new file.

## Setting up Google Cloud

Cicero uses your own Google Cloud project, so translations are billed to you
and your presentations go straight from your computer to Google. You need to do
this once.

1. **Create a project.** In the [Google Cloud console](https://console.cloud.google.com/),
   open the project picker at the top and click **New project**. Cloud
   Translation needs **billing** to be enabled on the project, even within the
   free allowance.
2. **Enable the API.** Go to **APIs & Services → Library**, search for
   **Cloud Translation API** and click **Enable**.
3. **Create a service account.** Go to **IAM & Admin → Service Accounts →
   Create service account**. Give it a name such as `cicero`, and grant it the
   role **Cloud Translation API User**. Nothing else is needed.
4. **Create a key.** Open the new service account, go to the **Keys** tab and
   choose **Add key → Create new key → JSON**. A `.json` file downloads: this is
   the **key file** Cicero asks for.

Keep the key file private. Anyone who has it can translate text on your bill.
See [Keeping your key safe](#keeping-your-key-safe).

> **Can't create keys?** Organisations often forbid service account keys (the
> policy `iam.disableServiceAccountKeyCreation`). Use Application Default
> Credentials instead: install the [gcloud CLI](https://cloud.google.com/sdk/docs/install), run
>
> ```bash
> gcloud auth application-default login
> gcloud auth application-default set-quota-project YOUR_PROJECT_ID
> ```
>
> then leave **Key file** empty in Cicero and click **Connect**. Your Google
> account needs the *Cloud Translation API User* role on the project.

## The window

![The Cicero window](images/screenshot.png)

### Google Cloud

- **Key file**: the service account key from the setup above. Choosing a file
  with **Browse…** connects straight away. If you type or paste a path, click
  **Connect**.
- Leave **Key file** empty to use Application Default Credentials (see the box
  above), or the file named by the `GOOGLE_APPLICATION_CREDENTIALS` environment variable.
- When the connection works, the line underneath shows the project and the
  number of languages available. Connecting only lists the languages; it doesn't
  translate anything and costs nothing.

Cicero remembers the key file's **location** and reconnects when it starts. It
never copies the key.

### Presentation

- **Translate**: the `.pptx` file to translate. Older `.ppt` files must first be
  opened in PowerPoint and saved as `.pptx`.
- **From**: the language the presentation is written in. *Detect automatically*
  works well for most presentations; pick the language yourself if the slides are
  mostly short labels, names or acronyms, which are hard to detect.
- **Into**: the language to translate into.
  Both boxes can be typed in: `span`, `Spanish` or `es` all find *Spanish (es)*.
  Regional variants have their own entries, e.g. *Portuguese (Portugal) (pt-PT)*
  and *Chinese (Traditional) (zh-TW)*.
- **Save as**: where to save the translation. It starts as
  `<original name> (<language code>).pptx` in the same folder, and follows your
  language choice until you choose another path yourself. It can't be the
  original file.
- **Also save a review spreadsheet**: also writes a `.csv` file with the same name
  as the translation. It has one row per paragraph: the slide number, where on
  the slide it is, the original and the translation. It opens in Excel or any
  spreadsheet program and is handy for a proofreader.

### Translating

Click **Translate**. The progress bar shows how many characters have been
translated. The window stays usable and you can click **Stop** at any time:
Cicero finishes the request already on its way to Google, then stops without
saving anything.

When it's done, a message shows where the translation was saved and offers to
open it.

## What gets translated

| Translated | Not translated |
|------------|----------------|
| Slide titles and placeholders | Text inside pictures |
| Text boxes and shapes, including inside groups (and groups of groups) | Charts (titles, labels, data) |
| Table cells | SmartArt |
| Speaker notes | Slide masters and layouts |
| | Comments |
| | Text with no letters: numbers, dates such as `2024`, symbols, bullets |

Each paragraph keeps its formatting. When a paragraph mixes formats (a bold word,
a link, a colour), Cicero tells the translator which words belong together and
puts each part of the translation back into the matching run. Because word order
changes between languages, the bold part may move within the sentence, which is
what you want. Occasionally the translator merges two parts; their text then
takes the formatting of the first one.

Translated text is often longer than the original (German and French are
typically 20–30 % longer than English). PowerPoint's *Shrink text on overflow*
setting helps; otherwise check slides with tight text boxes afterwards.

## Keeping your key safe

- Store the key file outside any folder that is synchronised publicly or
  committed to Git. This project's `.gitignore` ignores `*.json` to make
  accidents less likely.
- Never email the key or paste it into chat or tickets. Give each person their
  own service account or key instead, so one can be disabled without affecting the rest.
- If a key might have leaked, **delete it** in the Google Cloud console (**IAM & Admin →
  Service Accounts → *account* → Keys**) and create a new one. Deleting a key
  stops it working immediately, everywhere.
- Consider setting a budget alert under **Billing → Budgets & alerts**.

## Troubleshooting

**"The Cloud Translation API isn't enabled for project …"**
: Enable it under **APIs & Services → Library → Cloud Translation API**. It can
  take a minute or two to take effect.

**"The service account isn't allowed to use Cloud Translation"**
: Give the service account the **Cloud Translation API User** role under
  **IAM & Admin → IAM** in the same project the key belongs to.

**"Billing isn't enabled for project …"**
: Link a billing account to the project under **Billing**.

**"Google rejected the key"**
: The key was deleted or disabled, or its service account was removed. Create a new key.

**"This isn't a service account key"**
: You chose another kind of Google file, often an *OAuth client ID*
  (`client_secret_….json`). Create a service account key as described in
  [Setting up Google Cloud](#setting-up-google-cloud).

**"Can't write the file. Is it open in PowerPoint?"**
: Close the file in PowerPoint (or choose another **Save as** name) and try again.

**"This isn't a PowerPoint .pptx file, or it is damaged"**
: Cicero reads `.pptx` only. Open `.ppt` or `.odp` files in PowerPoint or
  LibreOffice Impress and save them as `.pptx`.

**"No module named tkinter" or "No module named _tkinter"** (Linux)
: Install Tkinter for your Python, e.g. `sudo apt install python3-tk`.

**Some text stayed in the original language**
: It is probably in a chart, SmartArt, a picture or the slide master (see
  [What gets translated](#what-gets-translated)), or it was in a language Google
  didn't detect: set **From** explicitly.

**I see `.….cicero-partial` files**
: They are left only if Cicero was killed while saving (for example from Task
  Manager or a power cut). They are safe to delete.
