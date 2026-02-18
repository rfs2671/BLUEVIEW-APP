import { ScrollViewStyleReset } from 'expo-router/html';

export default function Root({ children }) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
        <ScrollViewStyleReset />
        <script dangerouslySetInnerHTML={{
          __html: `
            if (!window.crypto || !window.crypto.subtle) {
              if (!window.crypto) window.crypto = {};
              window.crypto.subtle = {
                digest: async function() { return new ArrayBuffer(32); }
              };
              if (!window.crypto.getRandomValues) {
                window.crypto.getRandomValues = function(arr) {
                  for (var i = 0; i < arr.length; i++) arr[i] = Math.floor(Math.random() * 256);
                  return arr;
                };
              }
            }
          `
        }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
