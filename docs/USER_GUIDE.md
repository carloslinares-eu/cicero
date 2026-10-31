# Cicero user guide

Cicero makes a translated copy of a PowerPoint presentation (`.pptx`), a Word
document (`.docx`) or a PDF using Google Cloud Translation or DeepL. The original file is only ever
**read**; the translation is saved as a new file.

## Choosing a translation service

Cicero works with any of these; you only need one.

|           | Google Cloud Translation                                | DeepL                                                                                                                          | Local model                                    |
|-----------|---------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------|------------------------------------------------|
| Languages | About 190                                               | Fewer, but with regional variants (British/American English, Brazilian/European Portuguese); the list appears when you connect | 38 to 200+, depending on the model             |
| Cost      | A monthly free amount of characters, then per character | 500 000 characters a month free, then per character                                                                            | Free; uses your computer's electricity         |
| Setup     | Google Cloud project, API, service account key          | DeepL account and an authentication key                                                                                        | None: choose a model and click Download        |
| Privacy   | Your text goes to Google                                | Your text goes to DeepL                                                                                                        | Nothing leaves your computer                   |
| Speed     | Fast                                                    | Fast                                                                                                                           | A few seconds per paragraph on a graphics card |

With Google and DeepL your documents go straight from your computer to that service.
With a local model they never leave your computer.

## Setting up Google Cloud

Cicero uses your own Google Cloud project, so translations are billed to you.
You need to do this once.

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
See [Keeping your keys safe](#keeping-your-keys-safe).

> **Can't create keys?** Organizations often forbid service account keys (the
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

## Setting up DeepL

1. Sign up for the [DeepL API](https://www.deepl.com/pro-api). The **DeepL API
   Free** plan is enough to start; a regular DeepL (non-API) subscription doesn't
   include API access.
2. On deepl.com open **Account → API Keys** and copy your authentication key.
   Free-plan keys end in `:fx`; Cicero picks the right server from that.

Keep the key private, like a password.

## Local models

A local model is an open translation model that runs on your own computer,
ideally on its graphics card. Cicero offers four:

| Model                           | Download | Graphics memory | Good for                                                                                             |
|---------------------------------|----------|-----------------|------------------------------------------------------------------------------------------------------|
| **TranslateGemma 4B** (Google)  | 3.3 GB   | 8 GB            | Fast, 55 languages; the default                                                                      |
| **Hy-MT2 7B** (Tencent)         | 4.6 GB   | 8 GB            | Uses the surrounding text on each slide or page; 38 languages (many Asian ones, fewer European ones) |
| **Qwen 3.5 9B** (Alibaba)       | 6.6 GB   | 8 GB            | Reads the whole document first and keeps names and terms consistent; 200+ languages                  |
| **TranslateGemma 12B** (Google) | 8.1 GB   | 16 GB           | The best quality of the four                                                                         |

The note under the model says whether it fits your graphics card. A model that
doesn't fit still works: part of it runs on the processor, which is slower.

**Without a graphics card** (or with a small one, such as the 2 GB cards of older
laptops), a model runs in the computer's main memory, on the processor. It then needs
about as much memory as it takes on a graphics card (TranslateGemma 4B 2.9 GB, Hy-MT2
5.3 GB, Qwen 3.5 9B 5.6 GB) plus what the system uses, and the note says when a model
is too large for this computer's memory. With 8 GB of memory, use **TranslateGemma 4B**:
on a desktop processor it translates a paragraph in 2 to 4 seconds; an older laptop
takes several times as long, so a few pages take some minutes.

**Downloading.** Choose the model and click **Download**. The first time, Cicero
also downloads the engine that runs models (Ollama, 1.6 GB, once). The progress bar
shows both; **Cancel** pauses, and clicking **Download** again continues where it
stopped. When the model is ready a green **✔ Ready** appears and Cicero connects.
From then on Cicero connects by itself when it starts.

**Removing.** When a model is ready its button becomes **Remove…**, which deletes
it and frees its space. You can download it again at any time.

**Where things go.** The engine goes in Cicero's own folder
(`%LOCALAPPDATA%\Cicero` on Windows, `~/.local/share/cicero` on Linux,
`~/Library/Application Support/Cicero` on macOS). The models go where Ollama always keeps
them (`.ollama\models` in your user folder), so if you also use Ollama yourself,
both share the same downloads. If an Ollama is already running on your computer,
Cicero uses it instead of starting its own.

**Graphics cards.** NVIDIA cards work out of the box (driver 551.61 or newer).
For AMD cards Cicero also downloads Ollama's ROCm add-on; on Linux they also need
AMD's ROCm driver (see AMD's instructions for your distribution). Without a
suitable driver the model runs on the processor.

**Linux.** Local models work on Debian, Ubuntu, Fedora and other 64-bit
distributions (x86-64 and ARM). If you installed Ollama with its own installer, it
runs as a system service and Cicero uses it, with the models it already has.
Cicero itself needs Python with Tkinter (`python3-tk` on Debian/Ubuntu,
`python3-tkinter` on Fedora).

**While translating.** The engine runs hidden, only for Cicero, and stops when you
close Cicero. The first translation after starting takes a little longer while the
model loads into the graphics card. Each paragraph then takes a few seconds; a
40-slide presentation takes a few minutes.

**How Cicero gets better translations from local models.** Each model gets the
context it was trained to use:

- **Qwen 3.5** first reads the whole document (step *Reading the whole document*)
  and writes a short summary and a glossary of names, products and technical
  terms. Every paragraph is then translated with the summary, the glossary terms it
  contains, the earlier paragraphs on the same slide or page with their
  translations, and where it sits (a title, a table cell, the speaker notes…).
- **Hy-MT2** gets the earlier paragraphs on the same slide or page as background,
  in the format Tencent trained it with.
- **TranslateGemma** translates each paragraph on its own, with the exact prompt
  Google trained it with. It needs to know the language of the document: with
  *Detect automatically*, Cicero works it out from the whole document.

Bold words, links and other formatting inside a paragraph stay with the words they
belong to, as with Google and DeepL.

## The window

![The Cicero window](images/screenshot.png)

The header shows the version you are running (top right), which is useful when
reporting a problem.

### Translation service

- **Service**: *Google Cloud Translation*, *DeepL* or *Local model*. Switching
  connects to the other service straight away if Cicero already has its credentials
  (or, for a local model, if it's downloaded). The language
  boxes then show that service's languages, and each service remembers the
  languages you last used with it.

For Google Cloud Translation:

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

For DeepL:

- **Auth key**: paste the authentication key and click **Connect**. The line
  underneath shows your plan and how much of this period's character allowance
  you have used.
- **Remember**: keeps the key in the operating system's credential store
  (Windows Credential Manager, the macOS Keychain, or the Secret Service on
  Linux), never in a file, and reconnects when Cicero starts. Untick it and connect
  again to remove the stored key.

### Document

- **Translate**: the `.pptx`, `.docx` or `.pdf` file to translate. Older `.ppt` and `.doc`
  files must first be opened in PowerPoint or Word and saved as `.pptx` or `.docx`.
- **From**: the language the presentation is written in. *Detect automatically*
  works well for most presentations; pick the language yourself if the slides are
  mostly short labels, names or acronyms, which are hard to detect.
- **Into**: the language to translate into.
  Both boxes can be typed in: `span`, `Spanish` or `es` all find *Spanish (es)*.
  Regional variants have their own entries, e.g. *Portuguese (Portugal) (pt-PT)*
  and *Chinese (Traditional) (zh-TW)*.
- **Save as**: where to save the translation. It starts as
  `<original name> (<language code>).pptx` (or `.docx`, `.pdf`) in the same folder, and follows your
  language choice until you choose another path yourself. It can't be the
  original file.
- **Also save a review spreadsheet**: also writes a `.csv` file with the same name
  as the translation. It has one row per paragraph: the slide number, where on
  the slide it is, the original and the translation. It opens in Excel or any
  spreadsheet program and is handy for a proofreader.
- **Also translate slide masters and layouts**: the slide master and its layouts
  hold text that appears on every slide using them (a footer, a "Confidential"
  label, a section name) and the prompts PowerPoint shows in empty placeholders
  while you edit (*Click to edit Master title style*, *Click to add text*). Turn
  this on when the presentation is a template, or when that shared text is in the
  original language. Their rows in the review spreadsheet have slide number 0 and
  a location such as `Layout: Title Slide › Title 1`. Word documents and PDFs have
  no masters, so the option is greyed out for them.

### Translating

Click **Translate**. The progress bar shows how much of the text has been
translated, and the status bar at the bottom of the window counts:

- **Slide N of M**: the slide being translated.
- **Paragraph N of M**: paragraphs translated so far, out of all paragraphs found.
- **Characters**: what has been sent to Google so far, out of the total. This is
  what Google bills for.
- **Elapsed** and **about … left**: the time left is estimated from the speed so far,
  and appears once the first batch has come back.

When the job ends the status bar keeps the totals.

The window stays usable, and you can click **Stop** at any time:
Cicero finishes the request already on its way to Google, then stops without
saving anything.

When it's done, a message shows where the translation was saved and offers to
open it.

## What gets translated

### Presentations

| Translated                                                            | Not translated                                                        |
|-----------------------------------------------------------------------|-----------------------------------------------------------------------|
| Slide titles and placeholders                                         | Text inside pictures                                                  |
| Text boxes and shapes, including inside groups (and groups of groups) | Charts (titles, labels, data)                                         |
| Table cells                                                           | Comments                                                              |
| SmartArt                                                              |                                                                       |
| Speaker notes                                                         |                                                                       |
| Slide masters and layouts, if you ask for it (see below)              |                                                                       |
|                                                                       | Text with no letters: numbers, dates such as `2024`, symbols, bullets |

### Word documents

| Translated                             | Not translated                                                                      |
|----------------------------------------|-------------------------------------------------------------------------------------|
| Body text, headings, lists             | Text inside pictures                                                                |
| Tables, including tables inside tables | Charts and SmartArt                                                                 |
| Text boxes                             | Field codes (tables of contents and page numbers update when Word refreshes fields) |
| Headers and footers                    | Deleted text in tracked changes (insertions are translated)                         |
| Footnotes, endnotes and comments       | Text with no letters                                                                |

Word documents have no fixed pages (Word lays them out when it opens the file),
so the status bar shows paragraphs and characters only, and the review
spreadsheet has no page column; its *Location* says `Body`, `Body › Table`,
`Header`, `Footnotes` and so on.

### PDFs

A PDF has no paragraphs or text boxes, only letters placed on the page. Cicero
works out the paragraphs from how the lines sit, translates each one, removes the
original letters and writes the translation in the same place:

- Lines are joined into one paragraph only when the text was wrapped from one to
  the next. Table cells, a label and its value, a date beside a title, and the lines
  of an address each stay on their own, so a form or an invoice keeps its layout.
- Font size, bold, italic and color are kept for each part of the paragraph. The
  typeface is replaced by a standard one of the same kind (sans-serif, serif or
  monospaced), because PDFs usually contain only the letters their text uses.
- Left-, right- and center-aligned text keeps its alignment.
- Pictures, drawings, lines, backgrounds and shaded boxes are not touched.
- Longer translations first use the free space beside one-line text (to the right,
  or to the left of right-aligned text) and below every paragraph, without running
  into other text, pictures, ruled lines or out of a box the text sits in. Only if
  that isn't enough is the text made smaller. If it still doesn't fit, the end
  message says how many paragraphs may be cut off.
- Words hyphenated at the end of a line are joined before translating.

What isn't translated:

- **Postal addresses** (the lines that end in a postcode and town, and the name and
  street above them), and the names in them wherever they appear again: an address
  must stay valid, and names aren't translated.
- E-mail and web addresses, phone numbers, IBANs and other codes on their own.
- **Scanned PDFs** (pictures of pages) contain no text. Run them through OCR first,
  for example with Adobe Acrobat or [ocrmypdf](https://ocrmypdf.readthedocs.io/).
- A scanned letterhead under a document (its logo and footer): OCR software sometimes
  turns it into text drawn to look like the scan, which redrawn in another typeface
  would no longer look like it.
- Rotated or vertical text, text inside pictures, and form fields.
- **Password-protected PDFs** can't be opened; remove the password first.

The result is meant for reading. Complex layouts (several columns, text flowing
around pictures) can look less tidy than the original; when you have the source
document (Word or PowerPoint), translating that gives better results.

### Formatting

Each paragraph keeps its formatting. When a paragraph mixes formats (a bold word,
a link, a color), Cicero tells the translator which words belong together and
puts each part of the translation back into the matching run. Because word order
changes between languages, the bold part may move within the sentence, which is
what you want. Occasionally the translator merges two parts; their text then
takes the formatting of the first one.

Translated text is often longer than the original (German and French are
typically 20–30 % longer than English). PowerPoint's *Shrink text on overflow*
setting helps; otherwise check slides with tight text boxes afterward.

## Keeping your keys safe

- Store the key file outside any folder that is synchronised publicly or
  committed to Git. This project's `.gitignore` ignores `*.json` to make
  accidents less likely.
- Never email the key or paste it into chat or tickets. Give each person their
  own service account or key instead, so one can be disabled without affecting the rest.
- If a key might have leaked, **delete it** in the Google Cloud console (**IAM & Admin →
  Service Accounts → *account* → Keys**) and create a new one. Deleting a key
  stops it working immediately, everywhere.
- Consider setting a budget alert under **Billing → Budgets & alerts**.
- For DeepL, a leaked key can be deleted and replaced under **Account → API Keys**.
  DeepL also lets you set a cost control limit on Pro plans.

## Troubleshooting

**A local model is very slow**
: It probably doesn't fit in your graphics card and runs partly on the processor.
  The note under the model says so. Choose a smaller model, or close programs that
  use the graphics card (games, video editors, other AI tools).

**"Cicero couldn't tell which language the document is written in"**
: TranslateGemma needs the source language, and the document has too little text to
  tell. Choose it in **From**.

**A local model left some paragraphs untranslated**
: The model returned nothing for them; the message at the end says how many. Try
  another model, or translate that document with Google or DeepL.

**"Unpacking the engine needs zstd"** (Linux)
: Cicero installs the `zstandard` package for this; if it is missing, install
  `zstd` (`sudo apt install zstd` or `sudo dnf install zstd`) and try again.

**"The local model engine didn't start"
: The message names a log file (`ollama-server.log` in Cicero's folder) with the
  details. An outdated graphics driver is the usual cause: NVIDIA cards need driver
  551.61 or newer.

**"The Cloud Translation API isn't enabled for project …"**
: Enable it under **APIs & Services → Library → Cloud Translation API**. It can
  take a minute or two to take effect.

**"The service account isn't allowed to use Cloud Translation"**
: Give the service account the **Cloud Translation API User** role under
  **IAM & Admin → IAM** in the same project the key belongs to.

**"Billing isn't enabled for project …"**
: Link a billing account to the project under **Billing**.

**"DeepL rejected the authentication key"**
: Copy the key again from **Account → API Keys** on deepl.com. Keys from a regular
  DeepL subscription without API access don't work.

**"Your DeepL character quota for this period is used up"**
: Wait for the next period, upgrade the plan, or switch to Google Cloud Translation.

**A language I need isn't in the list**
: Each service supports its own set of languages. Switch the **Service** to the
  other one.

**"Google rejected the key"**
: The key was deleted or disabled, or its service account was removed. Create a new key.

**"This isn't a service account key"**
: You chose another kind of Google file, often an *OAuth client ID*
  (`client_secret_….json`). Create a service account key as described in
  [Setting up Google Cloud](#setting-up-google-cloud).

**"Can't write the file. Is it open in PowerPoint?"**
: Close the file in PowerPoint (or choose another **Save as** name) and try again.

**"This isn't a PowerPoint .pptx file" / "This isn't a Word .docx file"**
: Cicero reads `.pptx` and `.docx`. Open `.ppt`, `.doc`, `.odp` or `.odt` files in
  PowerPoint, Word or LibreOffice and save them as `.pptx` or `.docx`.

**"No module named tkinter" or "No module named _tkinter"** (Linux)
: Install Tkinter for your Python, e.g. `sudo apt install python3-tk`.

**Some text stayed in the original language**
: It is probably in a chart, SmartArt, a picture or the slide master (see
  [What gets translated](#what-gets-translated)), or it was in a language Google
  didn't detect: set **From** explicitly.

**"This PDF is password-protected"**
: Open it in a PDF reader and save or print it to a new PDF without a password.

**A translated PDF came out unchanged**
: It is probably a scan. See [PDFs](#pdfs).

**I see `.….cicero-partial` files**
: They are left only if Cicero was killed while saving (for example from Task
  Manager or a power cut). They are safe to delete.
