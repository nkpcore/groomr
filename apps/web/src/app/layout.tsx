import type { Metadata } from "next";
import { Newsreader, Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";

const displaySerif = Newsreader({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["400", "500", "600"],
});

const uiSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "CHAIR — Grooming Marketplace & Partner Operations",
  description: "Hybrid hyperlocal men's grooming marketplace and CHAIR Business partner console.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${displaySerif.variable} ${uiSans.variable}`}>
      <body className="min-h-screen bg-[#FAF7F2] font-sans text-[#1C1B19] antialiased">
        {children}
      </body>
    </html>
  );
}
