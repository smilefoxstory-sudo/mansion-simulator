import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "マンション修繕シミュレーター",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
