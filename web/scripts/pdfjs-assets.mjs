import { cpSync, mkdirSync } from 'node:fs'
import { resolve } from 'node:path'
// Keep PDF fonts, CMaps, image decoders and their upstream licenses on the Iris origin.
for (const directory of ['cmaps', 'standard_fonts', 'wasm']) {
 const target = resolve('public/pdfjs', directory)
 mkdirSync(target, {recursive:true})
 cpSync(resolve('node_modules/pdfjs-dist',directory),target,{recursive:true})
}
console.log('Local PDF preview assets prepared.')
