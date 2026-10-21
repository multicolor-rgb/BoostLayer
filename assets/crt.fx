// Boostlayer CRT shader for Gamescope's ReShade effect pipeline.
// The sampler has no explicit texture: Gamescope binds the compositor input to
// the first sampler, which keeps this effect self-contained (no ReShade.fxh).
sampler2D BackBuffer;

uniform float ScanlineStrength <
    ui_type = "slider";
    ui_min = 0.0;
    ui_max = 0.85;
    ui_label = "Scanline strength";
> = 0.34;

uniform float Curvature <
    ui_type = "slider";
    ui_min = 0.0;
    ui_max = 0.15;
    ui_label = "Screen curvature";
> = 0.045;

uniform float Vignette <
    ui_type = "slider";
    ui_min = 0.0;
    ui_max = 1.0;
    ui_label = "Vignette";
> = 0.42;

[shader("vertex")]
void CRTVertex(
    uint id : SV_VertexID,
    out float4 position : SV_Position,
    out float2 texcoord : TEXCOORD0)
{
    texcoord.x = (id == 2) ? 2.0 : 0.0;
    texcoord.y = (id == 1) ? 2.0 : 0.0;
    position = float4(texcoord * float2(2.0, -2.0) + float2(-1.0, 1.0), 0.0, 1.0);
}

[shader("pixel")]
float4 CRTPixel(
    float4 position : SV_Position,
    float2 texcoord : TEXCOORD0) : SV_Target
{
    float2 centered = texcoord * 2.0 - 1.0;
    float radius2 = dot(centered, centered);
    float2 warped = centered * (1.0 + Curvature * radius2);
    float2 uv = warped * 0.5 + 0.5;

    if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0)
        return float4(0.0, 0.0, 0.0, 1.0);

    float2 pixel = 1.0 / float2(BUFFER_WIDTH, BUFFER_HEIGHT);
    float3 color;
    color.r = tex2D(BackBuffer, uv + float2(pixel.x * 0.65, 0.0)).r;
    color.g = tex2D(BackBuffer, uv).g;
    color.b = tex2D(BackBuffer, uv - float2(pixel.x * 0.65, 0.0)).b;

    float scan = 0.5 + 0.5 * sin(uv.y * BUFFER_HEIGHT * 3.14159265);
    color *= 1.0 - ScanlineStrength * scan;

    float edge = smoothstep(0.45, 1.35, length(centered));
    color *= 1.0 - Vignette * edge;
    color = pow(max(color, 0.0), 1.04);
    return float4(color, 1.0);
}

technique CRT
{
    pass
    {
        VertexShader = CRTVertex;
        PixelShader = CRTPixel;
        VertexCount = 3;
    }
}
