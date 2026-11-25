# Wajeeha Document Crafter

A small Windows desktop app that drafts formal letters and applications with an AI model, lets you edit the result in a formatted preview, and saves it as an RTF file.

It is built for official correspondence in the style of Pakistani government letters, but the layout and prompts can be changed to suit other formats.

<img width="1600" height="858" alt="image" src="https://github.com/user-attachments/assets/6b2e8368-8499-444a-8222-48459d377868" />

## Features

- Enter the recipient, subject, date, sender details (name, post, section, organization).
- Connect to any OpenAI-compatible server, such as **LM Studio**, Ollama, or OpenAI.
- **Fetch Models** lists the models available on the server in a dropdown.
- Editable system and user prompts.
- Long timeout (7200 seconds) for slow local models.
- Live preview with a formatting toolbar: font, size, bold, italic, underline, alignment, indent, bullets, undo/redo.
- **Save as RTF** exports the preview exactly as you left it.
- Settings (server URL, API key, model, sender details, system prompt) are remembered in `crafter_config.json`.

## Repository layout

```
WajeehaDocumentCrafter/
├── document_crafter.py   # the application
├── requirements.txt          # no runtime dependencies
└── readme.md
```

## Requirements

- Python 3.9 or newer (Tkinter is included with the standard Windows installer from python.org).
- An OpenAI-compatible API server, for example LM Studio with its local server running.

## Running from source

```
python document_crafter.py
```

## Using with LM Studio

1. In LM Studio, load a model and start the local server (Developer tab).
2. In the app, set **Server API URL** to `http://localhost:1234/v1`.
3. Enter any text as the **API Key** (for example `lm-studio`).
4. Click **Fetch Models**, choose a model, and fill in the letter details.
5. Click **GENERATE DRAFT**, edit the preview if needed, then click **Save as RTF…**.

## Building a Windows executable

```
pip install pyinstaller
pyinstaller --onefile --windowed --name WajeehaDocumentCrafter document_crafter.py
```

The executable is created in `python/dist/`.

## Notes

- Formatting buttons act on the selected text. Select text first.
- If you generate a new draft after editing the preview, the app asks before replacing your changes.
- Do not commit `crafter_config.json` if it contains an API key you care about; add it to `.gitignore`.

## Suggested .gitignore

```
__pycache__/
*.pyc
build/
dist/
*.spec
crafter_config.json
```

## License

MIT
