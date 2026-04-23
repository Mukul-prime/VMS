import "./globals.css";
import Navbar from "@/components/Navbar";
import Sidebar from "@/components/Sidebar";

export const metadata = {
  title: "VMS Dashboard",
  description: "Video Management System",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body className="flex bg-gray-100">

        {/* Sidebar */}
        <div className="w-64 h-screen fixed">
          <Sidebar />
        </div>

        {/* Main Content */}
        <div className="flex-1 ml-64 flex flex-col">

          {/* Navbar */}
          <div className="sticky top-0 z-50">
            <Navbar />
          </div>

          {/* Page Content */}
          <main className="p-4">
            {children}
          </main>

        </div>

      </body>
    </html>
  );
}