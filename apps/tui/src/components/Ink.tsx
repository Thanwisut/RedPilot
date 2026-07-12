/** Thin wrappers around Ink's Box and Text with explicit layout props.
 *
 * Ink 5.2.1's type definitions don't expose all Yoga layout props
 * (marginTop, minWidth, etc.) on the component types. These wrappers
 * accept the subset we use and forward them at the `any` level, so
 * TypeScript strict mode is satisfied while Ink's runtime behavior is
 * preserved.
 */

import { Box as InkBox, Text as InkText } from "ink";
import type { ReactElement, ReactNode } from "react";

export interface BoxProps {
  children?: ReactNode;
  flexDirection?: "column" | "row" | "column-reverse" | "row-reverse";
  alignItems?: "flex-start" | "center" | "flex-end" | "stretch";
  justifyContent?:
    | "flex-start"
    | "center"
    | "flex-end"
    | "space-between"
    | "space-around"
    | "space-evenly";
  padding?: number;
  paddingX?: number;
  paddingY?: number;
  paddingTop?: number;
  paddingBottom?: number;
  paddingLeft?: number;
  paddingRight?: number;
  marginTop?: number;
  marginBottom?: number;
  marginLeft?: number;
  marginRight?: number;
  gap?: number;
  minWidth?: number;
  width?: number;
  height?: number;
  overflow?: "visible" | "hidden";
  borderStyle?:
    | "single"
    | "double"
    | "round"
    | "bold"
    | "singleDouble"
    | "doubleSingle"
    | "classic"
    | string;
  borderColor?: string;
  borderLeft?: boolean;
  borderRight?: boolean;
  borderTop?: boolean;
  borderBottom?: boolean;
  display?: "flex" | "none";
  flexGrow?: number;
  flexShrink?: number;
}

export function Box({ children, ...rest }: BoxProps): ReactElement {
  return <InkBox {...rest as any}>{children}</InkBox>;
}

export interface TextProps {
  children?: ReactNode;
  color?: string;
  backgroundColor?: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  strikethrough?: boolean;
  dimColor?: boolean;
  inverse?: boolean;
  minWidth?: number;
  wrap?: "wrap" | "truncate" | "truncate-end" | "truncate-middle" | "truncate-start";
  marginTop?: number;
  marginBottom?: number;
  gap?: number;
}

export function Text({ children, ...rest }: TextProps): ReactElement {
  return <InkText {...rest as any}>{children}</InkText>;
}
