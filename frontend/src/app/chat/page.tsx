import ChatInterface from "@/components/ChatInterface";
import Header from "@/components/Header";

export const metadata = {
  title: "Chat — Hawi الحاوي",
};

export default function ChatPage() {
  return (
    <main className="h-screen flex flex-col bg-gray-50 dark:bg-gray-950">
      <Header />
      <div className="flex-1 overflow-hidden">
        <ChatInterface />
      </div>
    </main>
  );
}
