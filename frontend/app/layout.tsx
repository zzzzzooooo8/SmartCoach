import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Coach",
  description: "AI 减脂教练",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
