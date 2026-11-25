import localFont from "next/font/local";
import "./globals.css";
import "@/styles/demand-ai.css";
import "katex/dist/katex.min.css";
import { Metadata } from "next/types";

const geistMono = localFont({
  src: [
    {
      path: "../../public/font/GeistMono-VariableFont_wght.ttf",
      style: "normal",
    },
    {
      path: "../../public/font/GeistMono-Italic-VariableFont_wght.ttf",
      style: "italic",
    },
  ],
  variable: "--font-geist-mono",
});

export const metadata: Metadata = {
  title: "Demand AI - Demand Forecasting",
  description: "Retail demand forecasting system and ingestion pipeline management",
  icons: {
    icon: [
      { url: "/icon.svg", type: "image/svg+xml" },
      { url: "/favicon.ico", sizes: "any" },
    ],
    apple: "/apple-icon.png",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistMono.variable} ${geistMono.variable} min-h-full flex flex-col antialiased`}
        suppressHydrationWarning
      >
        {children}
      </body>
    </html>
  );
}
