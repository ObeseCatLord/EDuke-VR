#version 410 compatibility
#extension GL_OVR_multiview2 : require

// This is the native Polymost vertex policy with the fixed-function camera
// transform replaced by the two saved XR eye transforms.  The vertex payload
// remains eye-specific: a_eye merely excludes the payload from the other
// multiview layer.
layout(num_views=2) in;

in float a_eye;

varying vec4 v_color;
varying float v_distance;

// u_texturePosSize is kept here so this source has the same visible interface
// as polymost1Vert.glsl.  The fragment shader owns the actual uniform use.
uniform vec4 u_texturePosSize;
uniform float u_usePalette;
uniform mat4 u_projection[2];
uniform mat4 u_rotation[2];

void main()
{
   int view = int(gl_ViewID_OVR);
   vec4 vertex = u_rotation[view] * gl_Vertex;
   vec4 eyeCoordPosition = vertex;
   gl_Position = u_projection[view] * vertex;

   // A finite, outside-the-frustum position makes an eye-owned payload
   // disappear from the other layer without depending on user clip planes.
   if (a_eye != float(view))
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
