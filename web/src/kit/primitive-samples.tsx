// The shadcn/ui primitives' states for /_kit (#295 R1): Button, Badge, Select,
// Toggle, Sheet and Dialog, Card and Separator, Skeleton. A chunk of its own (#299),
// so the kit's page stays under the route ceiling; kit.tsx only places it.
import { LinkIcon, SlidersHorizontalIcon } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { duration } from "@/lib/format";

import { NAMES } from "./samples";

function State({ name, children, wide = false }: { name: string; children: ReactNode; wide?: boolean }) {
  return (
    <div data-state-name={name} className={wide ? "w-full space-y-1" : "min-w-0 space-y-1"}>
      <p className="text-meta text-muted">{name}</p>
      <div className="flex min-h-11 flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function PrimitiveSamples() {
  const [shortSessions, setShortSessions] = useState(false);
  return (
    <>
    <State name="Button: default, outline, ghost, link, icon, disabled" wide>
      <Button>Compare laps</Button>
      <Button variant="outline">All sessions</Button>
      <Button variant="ghost">Clear</Button>
      <Button variant="link">Open the results card</Button>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="outline" size="icon" aria-label="Copy link">
            <LinkIcon aria-hidden="true" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>Copy link</TooltipContent>
      </Tooltip>
      <Button disabled>Compare laps</Button>
    </State>
    <State name="Badge: default, outline, muted" wide>
      <Badge>New best</Badge>
      <Badge variant="outline">12-lap race</Badge>
      <Badge variant="muted">session</Badge>
    </State>
    <State name="Select" wide>
      <Select defaultValue={NAMES.willow}>
        <SelectTrigger aria-label="Track" className="max-w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {[NAMES.willow, NAMES.tokyo, NAMES.gilles, NAMES.suzuka].map((n) => (
            <SelectItem key={n} value={n}>
              {n}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </State>
    <State name="Toggle: off and on" wide>
      <Toggle variant="outline" pressed={shortSessions} onPressedChange={setShortSessions}>
        Show short sessions
      </Toggle>
      <Toggle variant="outline" defaultPressed>
        Fuel
      </Toggle>
    </State>
    <State name="Sheet (from the bottom) and Dialog" wide>
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="outline">
            <SlidersHorizontalIcon aria-hidden="true" />
            Filters
          </Button>
        </SheetTrigger>
        <SheetContent>
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Narrow the list by track, car and kind.</SheetDescription>
          </SheetHeader>
          <SheetFooter>
            <SheetClose asChild>
              <Button>Show 12 sessions</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>
      <Dialog>
        <DialogTrigger asChild>
          <Button variant="outline">About this session</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>About this session</DialogTitle>
            <DialogDescription>
              Driven for {duration(596_826)} at {NAMES.willow}.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">Close</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </State>
    <State name="Card and Separator" wide>
      <Card className="w-full">
        <CardHeader>
          <CardTitle>Engineer</CardTitle>
          <CardDescription>Version 0.7.1, up 3 h 12 min</CardDescription>
        </CardHeader>
        <Separator />
        <CardContent className="text-sm text-muted">Telemetry connected. Voice joined.</CardContent>
      </Card>
    </State>
    <State name="Skeleton" wide>
      <Skeleton className="h-6 w-48" />
    </State>
    </>
  );
}
