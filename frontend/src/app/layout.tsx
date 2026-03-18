import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Company Intelligence",
  description: "Marketing AI — multi-agent company enrichment",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link
          href="https://api.fontshare.com/v2/css?f[]=clash-display@400,500,600,700&f[]=satoshi@400,500,700&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
        <style>{`
          :root {
            --font-clash: "Clash Display", system-ui, sans-serif;
            --font-satoshi: "Satoshi", system-ui, sans-serif;
          }
        `}</style>
      </head>
      <body className="font-body antialiased">{children}</body>
    </html>
  );
}
