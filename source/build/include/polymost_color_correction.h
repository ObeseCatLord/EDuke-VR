// Native Polymost shader color correction, shared with XR full-eye effects.
// Derived unchanged from polymost1Frag.glsl; see package/common/buildlic.txt.
#pragma once

namespace eduke_native_glsl
{
constexpr char ColorCorrection[] = R"glsl(
vec4 edukeColorCorrection(vec4 color, vec4 u_colorCorrection)
{
    const float c_one = 1.0;
    const vec2 c_vec2_zero_one = vec2(0.0, 1.0);
    const vec4 c_vec4_luma_709 = vec4(0.2126, 0.7152, 0.0722, 0.0);
    vec4 v_cc = vec4(u_colorCorrection.x - c_one, 0.5 * -(u_colorCorrection.y-c_one), -(u_colorCorrection.z-c_one), 1.0);
    return mat4(c_vec2_zero_one.yxxx, c_vec2_zero_one.xyxx, c_vec2_zero_one.xxyx, v_cc.xxxw)
                   * mat4(u_colorCorrection.ywww, u_colorCorrection.wyww, u_colorCorrection.wwyw, v_cc.yyyw)
                   * mat4((c_vec4_luma_709.xxxw * v_cc.z) + u_colorCorrection.zwww,
                          (c_vec4_luma_709.yyyw * v_cc.z) + u_colorCorrection.wzww,
                          (c_vec4_luma_709.zzzw * v_cc.z) + u_colorCorrection.wwzw,
                          c_vec2_zero_one.xxxy)
                   * color;
}
)glsl";
}
