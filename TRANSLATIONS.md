# UI translations

Supported languages and writing direction are declared in `app/assets/ui-languages.json`, shared by the API and web UI. The English source phrase is the message key. Hebrew catalogues live in `web/src/lib/locales`: interface copy, feedback, complete dynamic sentences, and controlled server messages. User content, names, provider diagnostics, URLs and technical identifiers remain verbatim.

Use `t('Complete sentence', {name: value})` for dynamic sentences; do not assemble translated words into English sentence order. Use logical CSS alignment (`start`, `end`, `text-start`) and keep identifiers in `bdi` or LTR inputs. Subscribe with `useLanguage()` when a component needs to react independently to a language change.

To add a language, add its metadata and complete message catalogue, register it in `locales/index.ts`, and extend the catalogue coverage checker for that language. The shared metadata also enables API validation and language selectors. English is the fallback for unsupported browser languages; the first browser preference selects the initial language. Authenticated preferences belong to the user record, not the browser.

Run `node scripts/check-translations.cjs` from `web`. The build runs this check before compilation. It detects missing static interface keys, empty translations and missing interpolation values. Review dynamic server messages and newly added status maps as part of UI changes; automated extraction cannot identify arbitrary runtime content.

Internal roles, statuses and category IDs must remain canonical values. Only their displayed labels are translated; the translation check rejects translated equality comparisons.

PDF documents are rendered by the bundled PDF.js worker on the Iris origin. The build copies its font, CMap and decoder assets with their upstream licenses. Other document formats remain authenticated downloads, never executable pages on the Iris origin.
