// Native build: phones draw tiles in a WebView page (SheetWebViewPane.native.jsx), never here.
// This placeholder exists so the shared code's `require('./SheetPane')` resolves on a phone;
// the web build uses SheetPane.web.jsx.
export default function SheetPane() { return null; }
