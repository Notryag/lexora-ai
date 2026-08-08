import type { Metadata, Viewport } from "next";

import { QueryProvider } from "./QueryProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "法析 Lexora",
  description: "AI 法律案例分析助手",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
