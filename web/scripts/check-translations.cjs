const fs = require('node:fs')
const path = require('node:path')
const ts = require('typescript')
const keys = new Set()
const errors = []
const parse = (file) =>
  ts.createSourceFile(
    file,
    fs.readFileSync(file, 'utf8'),
    ts.ScriptTarget.Latest,
    true,
    file.endsWith('tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  )
const visit = (node, fn) => {
  fn(node)
  ts.forEachChild(node, (n) => visit(n, fn))
}
for (const name of fs.readdirSync('src/lib/locales').filter((n) => /^he.*\.ts$/.test(n))) {
  visit(parse('src/lib/locales/' + name), (n) => {
    if (ts.isPropertyAssignment(n) && ts.isStringLiteral(n.initializer)) {
      const key = n.name.text
      keys.add(key)
      if (!n.initializer.text.trim()) errors.push('Empty translation: ' + key)
      const placeholders = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1])
      for (const p of placeholders(key))
        if (!placeholders(n.initializer.text).includes(p))
          errors.push('Missing placeholder ' + p + ': ' + key)
    }
  })
}
const neutral = new Set([
  'Iris',
  'SQLite',
  'MySQL',
  'PostgreSQL',
  'utf8mb4',
  'GreenAPI / WhatsApp',
  'Gmail',
  'STARTTLS',
  'SSL / TLS',
  'media',
  'OpenAI',
  'Ollama',
  'Cloudflare Workers AI',
  'docker restart iris',
  'gpt-4o-mini-transcribe',
  'whisper-1',
])
function walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const file = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      if (entry.name !== 'locales') walk(file)
      continue
    }
    if (!/\.tsx?$/.test(file)) continue
    const ast = parse(file)
    visit(ast, (n) => {
      if (
        ts.isBinaryExpression(n) &&
        [
          ts.SyntaxKind.EqualsEqualsEqualsToken,
          ts.SyntaxKind.ExclamationEqualsEqualsToken,
        ].includes(n.operatorToken.kind)
      ) {
        for (const operand of [n.left, n.right])
          if (
            ts.isCallExpression(operand) &&
            ['t', 'translate'].includes(operand.expression.getText(ast))
          )
            errors.push(`${file}: Translations must not be used in internal comparisons`)
      }
      let text
      if (ts.isJsxText(n)) text = n.getFullText(ast).trim().replace(/\s+/g, ' ')
      if (
        ts.isJsxAttribute(n) &&
        [
          'label',
          'title',
          'description',
          'hint',
          'placeholder',
          'aria-label',
          'alt',
          'what',
          'context',
          'confirmLabel',
        ].includes(n.name.text) &&
        n.initializer &&
        ts.isStringLiteral(n.initializer)
      )
        text = n.initializer.text
      if (
        ts.isCallExpression(n) &&
        ['t', 'translate'].includes(n.expression.getText(ast)) &&
        n.arguments[0] &&
        ts.isStringLiteral(n.arguments[0])
      )
        text = n.arguments[0].text
      if (
        !text ||
        !/[a-zA-Z\u0590-\u05ff]/.test(text) ||
        keys.has(text) ||
        neutral.has(text) ||
        /^(https?:\/\/|IRIS_)/.test(text)
      )
        return
      const pos = ast.getLineAndCharacterOfPosition(n.getStart(ast))
      errors.push(`${file}:${pos.line + 1}: Missing catalogue entry: ${text}`)
    })
  }
}
walk('src')
if (errors.length) {
  console.error(errors.join('\n'))
  process.exitCode = 1
} else console.log(`Translation coverage checked: ${keys.size} messages, Hebrew and English.`)
