// Preserve upstream notices when dependencies are bundled into the SPA.
import { readFileSync, readdirSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const lock = JSON.parse(readFileSync(resolve(root, 'package-lock.json'), 'utf8'))
const sections = [
  'Third-party notices for the Iris web build',
  'Dependency licenses remain their own licenses; the Iris MIT license does not replace them.',
  'Includes installed runtime dependencies. Build tools and model weights are not distributed with the SPA.',
]
for (const [path, entry] of Object.entries(lock.packages).sort(([a], [b]) => a.localeCompare(b))) {
  if (!path || entry.dev) continue
  const directory = resolve(root, path)
  // Optional binaries for other platforms are not installed or distributed by this build.
  if (!existsSync(directory)) continue
  const pkg = JSON.parse(readFileSync(resolve(directory, 'package.json'), 'utf8'))
  // PDF.js optionally uses native Canvas in Node; these binaries are never bundled into the browser SPA.
  if (pkg.name === '@napi-rs/canvas' || pkg.name.startsWith('@napi-rs/canvas-')) continue
  const notices = []
  if (pkg.name === 'react-remove-scroll-bar' && pkg.version === '2.3.8') {
    notices.push('Upstream LICENSE (package omits this file)\n' + readFileSync(resolve(root, 'licenses/react-remove-scroll-bar.LICENSE'), 'utf8'))
  }
  for (const file of readdirSync(directory, { withFileTypes: true })) {
    if (file.isFile() && /^(licen[cs]e|copying|notice)([.-].*)?$/i.test(file.name)) {
      notices.push(`${file.name}\n${readFileSync(resolve(directory, file.name), 'utf8')}`)
    }
    if (file.isDirectory() && /^(licenses|licences)$/i.test(file.name)) {
      for (const name of readdirSync(resolve(directory, file.name), { withFileTypes: true })) {
        if (name.isFile()) notices.push(`${file.name}/${name.name}\n${readFileSync(resolve(directory, file.name, name.name), 'utf8')}`)
      }
    }
  }
  if (!notices.length) throw new Error(`Missing license text for ${pkg.name}; review before distributing`)
  sections.push(`\n${'='.repeat(72)}\n${pkg.name} ${pkg.version}\nLicense: ${entry.license || pkg.license || 'See notices'}\n${notices.join('\n\n')}`)
}
mkdirSync(resolve(root, 'public'), { recursive: true })
writeFileSync(resolve(root, 'public/THIRD_PARTY_NOTICES.txt'), sections.join('\n\n') + '\n')
console.log('Third-party notices generated from installed package license files.')
