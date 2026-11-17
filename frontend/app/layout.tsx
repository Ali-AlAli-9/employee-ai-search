import type { Metadata } from "next";
import { Inter, Noto_Naskh_Arabic } from "next/font/google";
import { THEME_STORAGE_KEY } from "@/lib/theme";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const notoNaskh = Noto_Naskh_Arabic({
  subsets: ["arabic"],
  display: "swap",
  weight: ["400", "700"],
  variable: "--font-arabic",
});

export const metadata: Metadata = {
  title: "Employee AI Search",
  description: "Search your company documents and get answers with citations.",
};

const LANGUAGE_STORAGE_KEY = "eais-lang";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      dir="ltr"
      suppressHydrationWarning
      className={`${inter.variable} ${notoNaskh.variable}`}
    >
      <head>
        {/* Apply saved theme and direction before first paint to avoid a flash. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem(${JSON.stringify(
              THEME_STORAGE_KEY,
            )});if(t==='light')document.documentElement.setAttribute('data-theme','light');var l=localStorage.getItem(${JSON.stringify(
              LANGUAGE_STORAGE_KEY,
            )});if(l==='ar'){document.documentElement.lang='ar';document.documentElement.dir='rtl'}}catch(e){}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
