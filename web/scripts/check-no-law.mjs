#!/usr/bin/env node
// Acceptance check (FRONTEND_PLAN.md 7): no statute citation patterns typed into web/src.
// Mirrors: grep -rnE "§|Civ\. Code|G\.L\.|N\.J\.S\.A|Admin\. Code|P\.L\." web/src
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'src')
const pattern = /§|Civ\. Code|G\.L\.|N\.J\.S\.A|Admin\. Code|P\.L\./
const hits = []
function walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p)
    else
      fs.readFileSync(p, 'utf8')
        .split('\n')
        .forEach((line, i) => {
          if (pattern.test(line)) hits.push(`${path.relative(src, p)}:${i + 1}: ${line.trim()}`)
        })
  }
}
walk(src)
if (hits.length) {
  console.error('Law-like text found in web/src:\n' + hits.join('\n'))
  process.exit(1)
}
console.log('check-no-law: web/src is clean')
