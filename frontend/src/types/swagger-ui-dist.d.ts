declare module "swagger-ui-dist" {
  export interface SwaggerUIOptions {
    dom_id?: string;
    domNode?: HTMLElement;
    url?: string;
    spec?: unknown;
    deepLinking?: boolean;
    presets?: unknown[];
    plugins?: unknown[];
    layout?: string;
    docExpansion?: "list" | "full" | "none";
    filter?: boolean | string;
    displayRequestDuration?: boolean;
    showExtensions?: boolean;
    showCommonExtensions?: boolean;
    defaultModelsExpandDepth?: number;
    defaultModelExpandDepth?: number;
    [key: string]: unknown;
  }

  export function SwaggerUIBundle(options: SwaggerUIOptions): unknown;
  export namespace SwaggerUIBundle {
    export const presets: {
      apis: unknown;
    };
  }

  export const SwaggerUIStandalonePreset: unknown;
  export const absolutePath: () => string;
}
