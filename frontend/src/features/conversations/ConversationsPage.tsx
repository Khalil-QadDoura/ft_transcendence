import React, { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useText } from "../../i18n/useText";
import { ChatThread } from "./ChatThread";
import { ConversationList } from "./ConversationList";
import type { ConversationItem } from "./types";

export const ConversationsPage: React.FC = () => {
  const { t } = useText();
  const { id } = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const selectedConvId = id ? parseInt(id, 10) : null;
  const [selectedConversation, setSelectedConversation] =
    useState<ConversationItem | null>(null);

  const handleSelect = (conv: ConversationItem) => {
    setSelectedConversation(conv);
    navigate(`/chat/${conv.id}`);
  };

  return (
    <div
      className="mx-auto h-[calc(100vh-8rem)] max-w-6xl overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm dark:border-gray-800 dark:bg-gray-900"
      data-testid="conversations-page"
    >
      <div className="grid h-full grid-cols-1 md:grid-cols-12">
        {/* Conversations Sidebar List */}
        <div
          className={`h-full border-e border-gray-200 dark:border-gray-800 md:col-span-5 lg:col-span-4 ${
            selectedConvId ? "hidden md:block" : "block"
          }`}
        >
          <ConversationList
            selectedId={selectedConvId}
            onSelectConversation={handleSelect}
          />
        </div>

        {/* Conversation Thread Area */}
        <div
          className={`h-full md:col-span-7 lg:col-span-8 ${
            selectedConvId
              ? "block"
              : "hidden md:flex md:items-center md:justify-center"
          }`}
        >
          {selectedConvId ? (
            <ChatThread
              conversationId={selectedConvId}
              conversation={selectedConversation}
              onBack={() => navigate("/chat")}
            />
          ) : (
            <div
              className="p-8 text-center"
              data-testid="select-conversation-prompt"
            >
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
                <svg
                  className="h-7 w-7"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                  />
                </svg>
              </div>
              <h3 className="text-base font-medium text-gray-900 dark:text-gray-100">
                {t("chat.selectConversation")}
              </h3>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                {t("chat.selectConversationDesc")}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
