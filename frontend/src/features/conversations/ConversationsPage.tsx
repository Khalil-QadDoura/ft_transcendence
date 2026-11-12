import React, { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ConversationList } from "./ConversationList";
import type { ConversationItem } from "./types";

export const ConversationsPage: React.FC = () => {
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
          className={`h-full border-r border-gray-200 dark:border-gray-800 md:col-span-5 lg:col-span-4 ${
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
            selectedConvId ? "block" : "hidden md:flex md:items-center md:justify-center"
          }`}
        >
          {selectedConvId ? (
            <div className="flex h-full flex-col" data-testid="chat-thread-container">
              {/* Header with back button for mobile */}
              <div className="flex items-center space-x-3 border-b border-gray-100 p-4 dark:border-gray-800">
                <button
                  type="button"
                  onClick={() => navigate("/chat")}
                  className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 dark:text-gray-400 dark:hover:bg-gray-800 md:hidden"
                  data-testid="back-to-conversations-btn"
                >
                  <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                <div className="min-w-0 flex-1">
                  <h3 className="truncate text-base font-semibold text-gray-900 dark:text-gray-100">
                    {selectedConversation?.peer?.display_name ||
                      selectedConversation?.title ||
                      `Conversation #${selectedConvId}`}
                  </h3>
                  {selectedConversation?.job_title && (
                    <p className="truncate text-xs text-primary-600 dark:text-primary-400">
                      Applied for: {selectedConversation.job_title}
                    </p>
                  )}
                </div>
              </div>

              {/* Chat Thread Placeholder / Message History (FE-30) */}
              <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
                <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-primary-600 dark:bg-primary-950/50 dark:text-primary-400">
                  <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.5}
                      d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                    />
                  </svg>
                </div>
                <h4 className="text-base font-semibold text-gray-900 dark:text-gray-100">
                  Conversation Thread
                </h4>
                <p className="mt-1 max-w-sm text-xs text-gray-500 dark:text-gray-400">
                  Connected via WebSocket. Live message history and interactive messaging thread
                  ready.
                </p>
              </div>
            </div>
          ) : (
            <div className="p-8 text-center" data-testid="select-conversation-prompt">
              <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-gray-100 text-gray-400 dark:bg-gray-800 dark:text-gray-500">
                <svg className="h-7 w-7" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={1.5}
                    d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"
                  />
                </svg>
              </div>
              <h3 className="text-base font-medium text-gray-900 dark:text-gray-100">
                Select a conversation
              </h3>
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Choose a chat from the left sidebar to view messages and reply in real time.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
