import { useState } from "react";
import {
  Button,
  Input,
  Select,
  Textarea,
  Checkbox,
  Modal,
  ModalFooter,
  Avatar,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  Badge,
  Spinner,
  EmptyState,
  LoadMore,
  Pagination,
  Tabs,
  ToastProvider,
  useToast,
} from "../../components";

function PreviewDemo() {
  const [modalOpen, setModalOpen] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [checkboxChecked, setCheckboxChecked] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const toast = useToast();

  return (
    <div className="space-y-10 py-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-ink mb-2">
          Design System & Component Preview
        </h1>
        <p className="text-sm text-ink-muted">
          FE-21: Accessible, RTL-ready reusable UI components built on design tokens.
        </p>
      </div>

      {/* Buttons & Badges */}
      <Card>
        <CardHeader>
          <CardTitle>Buttons & Badges</CardTitle>
          <CardDescription>Various styles, loading states, and size variants.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary">Primary</Button>
            <Button variant="lime">Lime Brand</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="outline">Outline</Button>
            <Button variant="danger">Danger</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="primary" isLoading>Loading</Button>
            <Button variant="primary" disabled>Disabled</Button>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-2">
            <Badge variant="default">Default</Badge>
            <Badge variant="lime">Lime</Badge>
            <Badge variant="success">Success</Badge>
            <Badge variant="warning">Warning</Badge>
            <Badge variant="danger">Danger</Badge>
            <Badge variant="info">Info</Badge>
            <Badge variant="outline">Outline</Badge>
          </div>
        </CardContent>
      </Card>

      {/* Form Controls */}
      <Card>
        <CardHeader>
          <CardTitle>Form Controls</CardTitle>
          <CardDescription>Input, Select, Textarea, and Checkbox with ARIA labels and errors.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4 max-w-xl">
          <Input
            label="Full Name"
            placeholder="e.g. Ahmad Radwan"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            helperText="Enter your name as it appears on official documents."
          />

          <Input
            label="Email Address"
            placeholder="user@example.com"
            error="Invalid email address format."
            required
          />

          <Select
            label="Job Schedule"
            options={[
              { value: "full_time", label: "Full Time" },
              { value: "part_time", label: "Part Time" },
              { value: "internship", label: "Internship" },
            ]}
          />

          <Textarea
            label="Cover Note"
            placeholder="Write a brief note to the employer..."
            maxLength={1000}
            showCount
            rows={3}
          />

          <Checkbox
            label="Accept terms & privacy policy"
            description="You agree to our platform terms and video moderation guidelines."
            checked={checkboxChecked}
            onChange={(e) => setCheckboxChecked(e.target.checked)}
          />
        </CardContent>
      </Card>

      {/* Avatars & Spinners */}
      <Card>
        <CardHeader>
          <CardTitle>Avatars & Status Indicators</CardTitle>
          <CardDescription>Different sizes, fallbacks, and live status dots.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-4">
          <Avatar alt="Ahmad Radwan" size="lg" status="online" />
          <Avatar alt="Burhan" size="md" status="away" />
          <Avatar alt="Khalil" size="sm" status="offline" />
          <Avatar alt="Noob Thinker" size="xs" />
          <div className="flex items-center gap-2 ms-6">
            <Spinner size="sm" />
            <Spinner size="md" />
            <Spinner size="lg" />
          </div>
        </CardContent>
      </Card>

      {/* Interactive: Modal & Toast */}
      <Card>
        <CardHeader>
          <CardTitle>Feedback & Overlays</CardTitle>
          <CardDescription>Accessible focus-trapping modal and toast notification system.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          <Button variant="outline" onClick={() => setModalOpen(true)}>
            Open Dialog
          </Button>
          <Button
            variant="secondary"
            onClick={() => toast.success("Your changes have been saved!", "Success")}
          >
            Trigger Success Toast
          </Button>
          <Button
            variant="danger"
            onClick={() => toast.error("Could not upload video.", "Upload Failed")}
          >
            Trigger Error Toast
          </Button>
        </CardContent>
      </Card>

      {/* Tabs & Pagination */}
      <Card>
        <CardHeader>
          <CardTitle>Navigation & Pagination</CardTitle>
          <CardDescription>Tabs with keyboard support and page navigation.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <Tabs
            tabs={[
              {
                id: "tab1",
                label: "All Jobs",
                badge: <Badge size="sm" variant="lime">24</Badge>,
                content: <p className="text-sm text-ink-muted">List of active open job positions.</p>,
              },
              {
                id: "tab2",
                label: "My Applications",
                badge: <Badge size="sm" variant="default">3</Badge>,
                content: <p className="text-sm text-ink-muted">Overview of your submitted video applications.</p>,
              },
              {
                id: "tab3",
                label: "Archived",
                content: <EmptyState title="No archived items" description="Archived applications will appear here." />,
              },
            ]}
          />

          <Pagination
            currentPage={currentPage}
            totalPages={5}
            onPageChange={(page) => setCurrentPage(page)}
          />

          <LoadMore
            hasMore={true}
            onLoadMore={() => toast.info("Loading more jobs...")}
          />
        </CardContent>
      </Card>

      {/* Modal Instance */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Confirm Application"
        description="Are you sure you want to apply with your primary video resume?"
      >
        <p className="text-sm text-ink">
          The employer will be able to review your 30-second video and contact you directly via chat.
        </p>
        <ModalFooter>
          <Button variant="ghost" onClick={() => setModalOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="lime"
            onClick={() => {
              setModalOpen(false);
              toast.success("Application submitted successfully!");
            }}
          >
            Confirm & Send
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}

export function ComponentPreview() {
  return (
    <ToastProvider>
      <main className="max-w-4xl mx-auto px-4 py-8">
        <PreviewDemo />
      </main>
    </ToastProvider>
  );
}
