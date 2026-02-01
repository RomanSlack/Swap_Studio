import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Swap Studio",
  description: "AI-powered character swap and motion transfer",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
