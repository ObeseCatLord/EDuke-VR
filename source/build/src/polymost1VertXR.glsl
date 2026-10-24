#version 410 compatibility
#extension GL_OVR_multiview2 : require

// This is the native Polymost vertex policy with the fixed-function camera
// transform replaced by the two saved XR eye transforms.  The vertex payload
// remains eye-specific: a_eye merely excludes the payload from the other
// multiview layer.
// Foveated frames compile with XR_VIEWS 4: views 2 and 3 are the full-detail insets of the
// left and right eyes, cropped from the same projection (u_inset: scale xy, offset zw).
#ifndef XR_VIEWS
#define XR_VIEWS 2
#endif
layout(num_views=XR_VIEWS) in;

in float a_eye;

varying vec4 v_color;
varying float v_distance;

// u_texturePosSize is kept here so this source has the same visible interface
// as polymost1Vert.glsl.  The fragment shader owns the actual uniform use.
uniform vec4 u_texturePosSize;
uniform float u_usePalette;
uniform mat4 u_projection[2];
uniform mat4 u_rotation[2];
uniform mat4 u_modelview[2];
#if XR_VIEWS > 2
uniform vec4 u_inset[2];
#endif

void main()
{
   int view = int(gl_ViewID_OVR) & 1;
   vec4 vertex = u_rotation[view] * gl_Vertex;
   vec4 eyeCoordPosition = u_modelview[view] * vertex;
   // This uniform is native MVP: projection for identity-modelview ART,
   // GL-computed projection*modelview for an explicit native model.
   gl_Position = u_projection[view] * vertex;

   // A finite, outside-the-frustum position makes an eye-owned payload
   // disappear from the other layer without depending on user clip planes.
#if XR_VIEWS > 2
   if (gl_ViewID_OVR >= 2u)
      gl_Position.xy = gl_Position.xy*u_inset[view].xy + gl_Position.w*u_inset[view].zw;
#endif

   if (a_eye >= 0.0 && a_eye != float(view))
      gl_Position = vec4(2.0, 2.0, 2.0, 1.0);

   eyeCoordPosition.xyz /= eyeCoordPosition.w;

   gl_TexCoord[0] = gl_TextureMatrix[0] * gl_MultiTexCoord0;
   gl_TexCoord[0] = mix(gl_TexCoord[0].xyzw, gl_TexCoord[0].yxzw, u_usePalette);

   gl_TexCoord[3] = gl_TextureMatrix[3] * gl_MultiTexCoord3;
   gl_TexCoord[4] = gl_TextureMatrix[4] * gl_MultiTexCoord4;

   gl_FogFragCoord = abs(eyeCoordPosition.z);

   v_color = gl_Color;
   // Preserve raw reconstructed camera Z; the native fragment's indexed
   // palette and fog equations consume this exact varying.
   v_distance = gl_Vertex.z;
}
