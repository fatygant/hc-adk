# Pitch deck (PDF)

Źródło: `pitch.html` (5 slajdów 1920×1080, paleta Jutra z `jutra-front/styles/globals.css`).

Budowa:

```bash
make pitch
```

Tworzy `.venv` (jeśli brak), instaluje `[project.optional-dependencies] pitch` (Playwright), pobiera Chromium i zapisuje `pitch.pdf`.
