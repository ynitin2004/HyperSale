// The E2E suite in WebKit, the engine behind Safari, for machines with no Apple device (D44).
// This is not Safari: real-microphone and WebRTC behaviour still needs a real Safari run.
import { defineConfig } from '@playwright/test'
import base from './playwright.config'

export default defineConfig(base, { use: { ...base.use, browserName: 'webkit' } })
