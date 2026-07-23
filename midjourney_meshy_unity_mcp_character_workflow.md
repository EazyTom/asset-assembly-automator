# Midjourney → Meshy.ai → Rigged FBX → Unity + Unity MCP Character Workflow

**Goal:** Take a game character idea, generate clean T-pose concept art in Midjourney, convert it into a rigged FBX character in Meshy.ai, import it into Unity, configure the rig/animations, and use Unity MCP/Cursor-style prompts to automate parts of the pipeline.

**Best fit:** Stylized humanoid characters, NPCs, enemies, companions, and prototype game characters.

**Current caveat:** This workflow is useful for rapid prototyping and pre-production. For shipping-quality characters, expect manual cleanup in Blender/Maya and additional animation polish.

---

## 1. Recommended Pipeline Overview

```text
Idea / design brief
   ↓
Midjourney character-sheet prompts
   ↓
Clean T-pose front-view image
   ↓
Meshy Image to 3D with T-pose / A-pose enabled
   ↓
Meshy rigging + optional built-in animation export
   ↓
Export FBX + textures
   ↓
Unity import into Assets/Characters/<CharacterName>/
   ↓
Set Rig = Humanoid or Generic
   ↓
Configure Avatar + verify T-pose mapping
   ↓
Extract / assign animations
   ↓
Create Animator Controller
   ↓
Use Unity MCP to validate import, create prefab, place in scene, attach controller
```

---

## 2. Tool Roles

| Tool | Purpose | What to avoid |
|---|---|---|
| **Midjourney** | Create high-quality concept images and T-pose references | Avoid dynamic action poses, crossed limbs, weapons blocking body, extreme perspective |
| **Meshy.ai** | Convert image to 3D, generate T/A-pose, rig humanoid, export FBX/GLB | Avoid non-humanoid, hidden limbs, unclear silhouettes, huge capes/skirts without cleanup |
| **Unity** | Import FBX, configure rig/avatar, materials, animations, prefabs | Do not assume imported FBX is automatically game-ready |
| **Unity MCP** | Automate repetitive Unity Editor tasks through Cursor/Claude/other MCP clients | Use MCP for project automation, not for evaluating artistic quality without visual review |
| **Blender / Maya / Mixamo** | Optional cleanup, decimation, retargeting, animation fixes | Do not skip cleanup for production assets |

---

## 3. Character Design Rules for AI-to-3D

Meshy’s rigging works best on standard humanoid/bipedal models with clear limbs and body structure. Design your prompts around that.

### Good character inputs

- Clear front-facing character.
- Arms slightly away from body.
- Legs separated enough to see silhouette.
- Symmetrical costume.
- No crossed arms.
- No huge weapon covering torso.
- No cloak hiding legs.
- No busy background.
- No extreme foreshortening.
- Full body visible from head to feet.

### Bad character inputs

- Three-quarter cinematic pose.
- Sitting/kneeling/crouching poses.
- Creature with four arms, wings, tentacles, or no legs.
- Large props fused to hands/body.
- Hair covering shoulders and arms.
- Robes or skirts that obscure leg separation.
- Dynamic lighting that hides silhouette.

---

## 4. Midjourney Prompt Strategy

The most important step is generating a clean T-pose image. Do not start with a cinematic pose and hope Meshy fixes it. Ask Midjourney for a **front orthographic T-pose character sheet**.

### Core prompt formula

```text
[character identity], full body T-pose, front view, orthographic character sheet, symmetrical design, arms straight out horizontally, legs slightly apart, clean silhouette, game-ready character concept art, neutral expression, plain white background, no weapons, no props, no text, no watermark --ar 2:3 --style raw --v 6.1
```

If your Midjourney version differs, adjust `--v` accordingly.

---

## 5. Midjourney Example Prompts

### 5.1 Stylized fantasy hero

```text
stylized fantasy swamp ranger, full body T-pose, front view, orthographic character sheet, symmetrical leather armor, arms straight out horizontally, legs slightly apart, clean silhouette, neutral expression, game-ready 3D character concept art, Pixar-meets-Zelda style, plain white background, no weapon, no props, no text, no watermark --ar 2:3 --style raw --v 6.1
```

### 5.2 Cyberpunk NPC

```text
cyberpunk street courier NPC, full body T-pose, front orthographic view, symmetrical jacket and utility pants, arms straight out horizontally, palms down, legs slightly apart, clean silhouette, game-ready character concept, high resolution, plain gray background, no props, no text, no watermark --ar 2:3 --style raw --v 6.1
```

### 5.3 Creature-like but still humanoid enemy

```text
humanoid mushroom goblin enemy, bipedal body, full body T-pose, front orthographic view, arms straight out horizontally, legs visible and slightly apart, clear humanoid skeleton structure, stylized game enemy concept art, clean silhouette, plain white background, no props, no text --ar 2:3 --style raw --v 6.1
```

### 5.4 Child-friendly companion character

```text
cute stylized helper character, small humanoid adventurer, full body T-pose, front orthographic view, arms straight out horizontally, legs slightly apart, clean rounded silhouette, colorful simple clothing, game-ready character concept art, plain white background, no props, no text, no watermark --ar 2:3 --style raw --v 6.1
```

### 5.5 Strong negative prompt add-on

Add this to prompts when Midjourney keeps producing bad poses:

```text
--no action pose, running, jumping, sitting, crouching, crossed arms, weapon, sword, staff, shield, cape covering body, cropped feet, cropped hands, background scene, text, logo, watermark
```

---

## 6. Midjourney Output Selection Checklist

Pick an image only if it passes most of these checks:

- Full body is visible.
- Feet and hands are not cropped.
- Body faces forward.
- Arms are extended or at least separated from torso.
- Legs are visible.
- Outfit is not hiding all limb structure.
- Character is mostly symmetrical.
- Background is plain or easy to remove.
- There is no text or watermark.
- No major props are fused into the body.

If the character is not in a clean T-pose, generate again rather than trying to fix downstream.

---

## 7. Optional Image Prep Before Meshy

Before uploading to Meshy, optionally process the image:

1. Crop to full body with a little padding around head, hands, and feet.
2. Remove background if it is busy.
3. Keep the image high resolution.
4. Avoid over-sharpening.
5. Save as PNG or high-quality JPG.
6. Name file clearly:

```text
SwampRanger_TPose_Front_v01.png
```

Recommended folder:

```text
/ArtSource/Characters/SwampRanger/Midjourney/
```

---

## 8. Meshy.ai Image-to-3D Workflow

### 8.1 Manual Meshy workflow

1. Open Meshy.ai.
2. Choose **Image to 3D**.
3. Upload the selected Midjourney T-pose image.
4. Enable **A/T Pose** or choose **T-pose** if available.
5. Enable texture generation.
6. Enable PBR if you want physically based materials.
7. Enable remesh if available.
8. Use a higher target polycount for better source quality, then reduce later if needed.
9. Generate several candidates.
10. Select the best model based on silhouette, face, limbs, and texture quality.
11. Use Meshy rigging/animation if available for the selected model.
12. Export as **FBX** for Unity character workflow.
13. Also export **GLB** as a backup/reference when useful.

### 8.2 Meshy settings to prefer

| Setting | Recommended value |
|---|---|
| Input mode | Image to 3D |
| Pose | T-pose, or A-pose if T-pose performs poorly |
| Texture | Enabled |
| PBR | Enabled for URP/HDRP workflows |
| Remesh | Enabled if available |
| Target polycount | 50k–100k for source; reduce later for runtime |
| Export | FBX + textures; GLB backup |
| Rig type | Humanoid/biped where possible |
| Animations | Export included walk/run/idle clips if available |

---

## 9. Meshy Prompt Examples

Meshy may use prompt guidance differently depending on the current UI/API mode, but these examples are useful when a text field is available.

### 9.1 General Meshy generation prompt

```text
Create a clean game-ready humanoid 3D character from this image. Preserve the character identity, colors, costume, and silhouette. Generate in a standard T-pose suitable for humanoid rigging and Unity import. Keep limbs clearly separated, maintain clean topology, and produce PBR textures.
```

### 9.2 Rigging prompt

```text
Rig this as a standard humanoid biped character for Unity. Use a clean skeleton suitable for humanoid animation retargeting. Preserve mesh deformation around shoulders, elbows, hips, and knees. Include basic idle, walk, run, and jump animations if available.
```

### 9.3 Lower-poly game asset prompt

```text
Optimize this character as a stylized real-time game asset. Keep the silhouette and readable costume details, but avoid excessive geometry. Use clean UVs, baked texture details, and a Unity-friendly FBX export.
```

---

## 10. Optional Meshy API Pattern

Meshy’s Image to 3D API supports creating an image-to-3D task from an image URL or base64 data URI. Its current API includes `pose_mode` values such as `a-pose` and `t-pose`, and the older `is_a_t_pose` field is deprecated.

### Example API request pattern

```bash
curl https://api.meshy.ai/openapi/v1/image-to-3d \
  -X POST \
  -H "Authorization: Bearer ${MESHY_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "image_url": "<public_image_url_or_base64_data_uri>",
    "enable_pbr": true,
    "should_remesh": true,
    "target_polycount": 100000,
    "should_texture": true,
    "pose_mode": "t-pose",
    "target_formats": ["fbx", "glb"]
  }'
```

### Retrieve task result

```bash
curl https://api.meshy.ai/openapi/v1/image-to-3d/<TASK_ID> \
  -H "Authorization: Bearer ${MESHY_API_KEY}"
```

### Notes

- Store Meshy API keys in environment variables or secrets.
- Do not commit API keys to Unity, GitHub, or MCP config files.
- If `fbx` is not supported in your selected endpoint/settings, export GLB and convert through Blender, or use the Meshy UI export.

---

## 11. Meshy Rigging Notes

Meshy rigging is best suited for standard humanoid/biped assets. Avoid expecting clean auto-rigging for non-humanoid characters, untextured meshes, or designs where limbs are unclear.

Recommended character constraints:

- Two arms.
- Two legs.
- One head.
- Visible elbows/knees.
- No fused geometry between arms and torso.
- No large cloth hiding legs.
- Minimal dangling accessories.

If the rig result is poor:

1. Regenerate Midjourney image with clearer T-pose.
2. Try A-pose instead of T-pose.
3. Remove capes/props/hair obstruction.
4. Regenerate Meshy model.
5. Clean in Blender.
6. Use Mixamo/Blender/Rigify as a fallback rigging path.

---

## 12. Export Package Structure

When downloading from Meshy, organize files like this:

```text
Assets/
  Characters/
    SwampRanger/
      Source/
        SwampRanger_meshy_v01.fbx
        SwampRanger_meshy_v01.glb
      Textures/
        SwampRanger_BaseColor.png
        SwampRanger_Normal.png
        SwampRanger_MetallicRoughness.png
      Materials/
      Animations/
      Prefabs/
      Controllers/
```

Keep original Meshy exports untouched in `Source/` and create Unity-specific assets in sibling folders.

---

## 13. Unity Import: Manual Steps

### 13.1 Import FBX

1. Copy the FBX and texture files into:

```text
Assets/Characters/<CharacterName>/Source/
Assets/Characters/<CharacterName>/Textures/
```

2. Let Unity import the FBX.
3. Select the FBX in Project view.

### 13.2 Configure Rig tab

For humanoid characters:

1. Select the FBX.
2. Go to **Inspector → Rig**.
3. Set **Animation Type** to **Humanoid**.
4. Set **Avatar Definition** to **Create From This Model**.
5. Click **Apply**.
6. Click **Configure**.
7. Verify bone mapping.
8. Enforce/verify T-pose if needed.
9. Click **Done**.

For non-standard characters:

1. Set **Animation Type** to **Generic**.
2. Select the root bone.
3. Click **Apply**.

### 13.3 Configure Materials

1. Select the FBX.
2. Go to **Materials** tab.
3. Extract materials to:

```text
Assets/Characters/<CharacterName>/Materials/
```

4. Assign textures manually if needed.
5. For URP, use **Universal Render Pipeline/Lit**.
6. Assign base color, normal, metallic/roughness maps.

### 13.4 Configure Animation tab

1. Select the FBX.
2. Go to **Animation** tab.
3. Enable **Import Animation**.
4. Review imported clips.
5. Rename clips clearly:

```text
Idle
Walk
Run
Jump
Attack
```

6. For looping clips, enable **Loop Time**.
7. Click **Apply**.

---

## 14. Unity Animator Setup

### 14.1 Create folders

```text
Assets/Characters/<CharacterName>/Controllers/
Assets/Characters/<CharacterName>/Prefabs/
```

### 14.2 Create Animator Controller

1. Right-click `Controllers/`.
2. Create → Animator Controller.
3. Name it:

```text
AC_<CharacterName>
```

4. Open Animator window.
5. Add states:

```text
Idle
Walk
Run
Jump
Attack
```

6. Set `Idle` as default state.
7. Add parameters:

```text
Speed : Float
IsGrounded : Bool
Jump : Trigger
Attack : Trigger
```

### 14.3 Basic transitions

| From | To | Condition |
|---|---|---|
| Idle | Walk | Speed > 0.1 |
| Walk | Idle | Speed < 0.1 |
| Walk | Run | Speed > 3.5 |
| Run | Walk | Speed < 3.5 |
| Any State | Jump | Jump trigger |
| Any State | Attack | Attack trigger |

### 14.4 Add Animator to character

1. Drag the FBX model into the scene.
2. Add/verify **Animator** component.
3. Assign `AC_<CharacterName>`.
4. Verify Avatar is assigned.
5. Create prefab:

```text
Assets/Characters/<CharacterName>/Prefabs/PF_<CharacterName>.prefab
```

---

## 15. Simple Unity Character Animation Test Script

Create:

```text
Assets/Scripts/CharacterAnimationTester.cs
```

```csharp
using UnityEngine;

public class CharacterAnimationTester : MonoBehaviour
{
    [SerializeField] private Animator animator;
    [SerializeField] private float walkSpeed = 1.0f;
    [SerializeField] private float runSpeed = 4.0f;

    private void Reset()
    {
        animator = GetComponent<Animator>();
    }

    private void Update()
    {
        if (animator == null) return;

        float speed = 0f;

        if (Input.GetKey(KeyCode.W))
        {
            speed = Input.GetKey(KeyCode.LeftShift) ? runSpeed : walkSpeed;
        }

        animator.SetFloat("Speed", speed);

        if (Input.GetKeyDown(KeyCode.Space))
        {
            animator.SetTrigger("Jump");
        }

        if (Input.GetMouseButtonDown(0))
        {
            animator.SetTrigger("Attack");
        }
    }
}
```

Attach this to the character prefab and assign the Animator.

---

## 16. Unity MCP Workflow

Unity MCP can connect LLM clients such as Cursor or Claude Code to the Unity Editor through standardized MCP tools. Depending on whether you use Unity’s official MCP support or a community MCP server, exact tool names may differ.

Use MCP for tasks like:

- Finding imported assets.
- Creating folders.
- Creating prefabs.
- Reading console logs.
- Creating materials.
- Assigning materials.
- Creating scenes.
- Placing prefabs in scenes.
- Running validation scripts.
- Triggering custom C# import tools.

---

## 17. Unity MCP Prompt Examples

### 17.1 Find imported character assets

```text
Find all assets under Assets/Characters/SwampRanger. Identify the FBX, textures, materials, animation clips, prefabs, and animator controllers. Report anything missing from the expected character folder structure.
```

### 17.2 Create folder structure

```text
Create the folder structure for a new character named SwampRanger:
Assets/Characters/SwampRanger/Source
Assets/Characters/SwampRanger/Textures
Assets/Characters/SwampRanger/Materials
Assets/Characters/SwampRanger/Animations
Assets/Characters/SwampRanger/Controllers
Assets/Characters/SwampRanger/Prefabs
Then save the project.
```

### 17.3 Validate FBX import

```text
Inspect the FBX at Assets/Characters/SwampRanger/Source/SwampRanger_meshy_v01.fbx. Confirm whether Unity imported a SkinnedMeshRenderer, Animator, Avatar, materials, and animation clips. Show any console errors or warnings related to this asset.
```

### 17.4 Create character prefab

```text
Create a prefab named PF_SwampRanger from the imported SwampRanger FBX. Place it in Assets/Characters/SwampRanger/Prefabs. Ensure it has an Animator component assigned to AC_SwampRanger if that controller exists.
```

### 17.5 Create animation test scene

```text
Create a new scene called CharacterTest_SwampRanger in Assets/Scenes. Add a plane, a directional light, a camera, and the PF_SwampRanger prefab at world origin. Position the camera so the full character is visible. Save the scene.
```

### 17.6 Check console logs

```text
Show the last 30 Unity console logs and filter for warnings or errors related to SwampRanger, FBX import, Avatar configuration, materials, textures, or animation clips.
```

### 17.7 Generate helper script

```text
Create a C# script named CharacterAnimationTester in Assets/Scripts. It should drive an Animator with Speed float, Jump trigger, and Attack trigger using keyboard input. Attach it to PF_SwampRanger and assign the Animator reference.
```

### 17.8 Create custom importer task

```text
Create an Editor utility script that configures character FBX imports under Assets/Characters. It should set humanoid rigs where possible, enable animation import, extract materials to a Materials folder, and log validation results. Do not overwrite existing manually configured assets without confirmation.
```

---

## 18. Optional Custom Unity Editor Importer

For repeatable imports, create a Unity Editor script that applies model import conventions. This can later be exposed through Unity MCP as a custom tool.

Create:

```text
Assets/Editor/CharacterFbxImportUtility.cs
```

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

public static class CharacterFbxImportUtility
{
    [MenuItem("Tools/Characters/Configure Selected FBX As Humanoid")]
    public static void ConfigureSelectedFbxAsHumanoid()
    {
        Object selected = Selection.activeObject;
        if (selected == null)
        {
            Debug.LogWarning("No FBX selected.");
            return;
        }

        string path = AssetDatabase.GetAssetPath(selected);
        if (string.IsNullOrEmpty(path) || !path.ToLowerInvariant().EndsWith(".fbx"))
        {
            Debug.LogWarning($"Selected asset is not an FBX: {path}");
            return;
        }

        ModelImporter importer = AssetImporter.GetAtPath(path) as ModelImporter;
        if (importer == null)
        {
            Debug.LogWarning($"Could not get ModelImporter for: {path}");
            return;
        }

        importer.animationType = ModelImporterAnimationType.Human;
        importer.avatarSetup = ModelImporterAvatarSetup.CreateFromThisModel;
        importer.importAnimation = true;
        importer.importMaterials = true;
        importer.SaveAndReimport();

        Debug.Log($"Configured FBX as Humanoid with imported animations: {path}");
    }
}
#endif
```

Then ask Unity MCP:

```text
Execute the menu item Tools/Characters/Configure Selected FBX As Humanoid for the currently selected FBX, then show any import warnings or errors from the Unity console.
```

---

## 19. Animation Retargeting Notes

If Meshy exports humanoid-compatible animations:

1. Import the animated FBX.
2. Set rig to Humanoid.
3. Configure Avatar.
4. Extract or duplicate clips if needed.
5. Assign clips to Animator Controller states.

If animations come in a separate FBX:

1. Import character FBX first.
2. Configure character Avatar.
3. Import animation FBX.
4. Set animation FBX Rig → Humanoid.
5. Use **Avatar Definition: Copy From Other Avatar**.
6. Select the character Avatar.
7. Apply.
8. Use clips in Animator Controller.

If retargeting breaks:

- Verify both source and target use Humanoid.
- Check T-pose alignment in Avatar Configure mode.
- Confirm hips/spine/head/arms/legs are mapped.
- Try Generic if character is not truly humanoid.
- Fix bone names/pose in Blender if needed.

---

## 20. Runtime Optimization Checklist

Before using in a real game scene:

- Reduce polygon count if too high.
- Compress textures.
- Limit texture size, often 2K or 1K for prototypes.
- Generate LODs for repeated characters.
- Check SkinnedMeshRenderer bounds.
- Remove unused bones if possible.
- Merge materials where reasonable.
- Use GPU instancing only where applicable.
- Profile animation cost.
- Test on target hardware, especially Quest/mobile.

Recommended Unity texture defaults for prototypes:

| Asset type | Max size |
|---|---:|
| Main character | 2048 |
| NPC | 1024–2048 |
| Small enemy | 1024 |
| Background crowd | 512–1024 |

---

## 21. Quality Control Checklist

### Mesh quality

- No holes in body.
- Fingers are not fused badly.
- Feet contact ground naturally.
- Face is recognizable.
- Costume details are not melted into body.
- Normal map is not inverted.
- Materials look correct in target render pipeline.

### Rig quality

- Shoulders deform acceptably.
- Elbows bend correctly.
- Knees bend forward.
- Hips do not collapse.
- Head rotates cleanly.
- Feet stay near ground in walk/run.
- No major mesh explosions during animation.

### Unity quality

- Avatar is valid.
- Animator Controller plays default idle.
- Animation transitions work.
- Prefab is saved.
- Console has no import errors.
- Materials are assigned.
- Textures are not pink/missing.

---

## 22. Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| Meshy creates bad body shape | Midjourney pose too cinematic | Regenerate clean front T-pose |
| Arms fused to torso | Arms too close to body | Prompt for arms straight out and clear silhouette |
| Unity Humanoid Avatar invalid | Bone mapping incomplete | Configure Avatar manually or use Generic |
| Animations distort mesh | Bad weights or auto-rig | Regenerate rig, clean in Blender, or use Mixamo/Rigify |
| Materials are pink | Shader/render pipeline mismatch | Convert materials to URP/HDRP Lit |
| Textures missing | FBX did not embed/extract textures | Copy textures into Textures folder and reassign |
| Character too heavy | High polycount/PBR texture size | Decimate/remesh, compress textures, create LODs |
| Animation clips missing | FBX export did not include animation | Re-export animated FBX from Meshy or separate animation files |
| MCP cannot see assets | Project not refreshed or MCP disconnected | Refresh AssetDatabase, check MCP bridge, check console |

---

## 23. Production Upgrade Path

For a more serious game-development pipeline:

1. Use Midjourney for initial concept only.
2. Generate Meshy prototype character.
3. Bring FBX/GLB into Blender.
4. Clean mesh topology.
5. Retopologize if needed.
6. Fix UVs/materials.
7. Rig with Rigify, Auto-Rig Pro, Mixamo, or custom skeleton.
8. Export Unity-ready FBX.
9. Use Unity MCP to automate import validation.
10. Store source files and Unity prefabs in version control or asset management.

---

## 24. Suggested Naming Conventions

```text
CHR_<CharacterName>_Concept_TPose_v01.png
CHR_<CharacterName>_Meshy_Source_v01.fbx
MAT_<CharacterName>_Body.mat
TEX_<CharacterName>_BaseColor.png
TEX_<CharacterName>_Normal.png
ANIM_<CharacterName>_Idle.anim
ANIM_<CharacterName>_Walk.anim
AC_<CharacterName>.controller
PF_<CharacterName>.prefab
SCN_CharacterTest_<CharacterName>.unity
```

---

## 25. End-to-End Example: Swamp Ranger

### Step 1: Midjourney prompt

```text
stylized fantasy swamp ranger, full body T-pose, front view, orthographic character sheet, symmetrical leather armor with moss and brass details, arms straight out horizontally, legs slightly apart, clean silhouette, neutral expression, game-ready 3D character concept art, plain white background, no weapon, no props, no text, no watermark --ar 2:3 --style raw --v 6.1 --no action pose, crossed arms, sword, staff, shield, cape covering body, cropped feet, cropped hands
```

### Step 2: Meshy prompt

```text
Create a clean game-ready humanoid 3D character from this image. Preserve the swamp ranger identity, mossy leather armor, brass details, and stylized proportions. Generate in a standard T-pose for Unity humanoid rigging. Keep limbs clearly separated and produce PBR textures.
```

### Step 3: Meshy export

Export:

```text
SwampRanger_meshy_v01.fbx
SwampRanger_meshy_v01.glb
Textures/*.png
```

### Step 4: Unity import path

```text
Assets/Characters/SwampRanger/Source/SwampRanger_meshy_v01.fbx
Assets/Characters/SwampRanger/Textures/
```

### Step 5: Unity MCP command

```text
Inspect Assets/Characters/SwampRanger. Configure the FBX as a humanoid character if possible, create AC_SwampRanger, create PF_SwampRanger, place it in a new CharacterTest_SwampRanger scene, and show any console warnings or errors.
```

---

## 26. Source Notes

- Meshy Image to 3D API supports image-to-3D task creation and includes `pose_mode` options such as `a-pose` and `t-pose`; `is_a_t_pose` is deprecated in favor of `pose_mode`.
- Meshy Rigging API is intended for adding skeletons to humanoid models and notes that programmatic rigging currently works best with standard humanoid bipedal assets with clear limbs and body structure.
- Unity’s humanoid animation import flow maps model bones to a Humanoid Avatar, and Unity recommends defining the rig type, verifying Avatar mapping, importing animation, and defining clips where needed.
- Unity MCP connects LLM-based agents such as Cursor or Claude Code to Unity Editor through standardized MCP tools for project, scene, asset, script, and console workflows.
- Community Unity MCP implementations commonly expose tools/resources for assets, console logs, scene operations, prefabs, materials, and custom Editor tooling.

## 27. References

- Meshy Image to 3D API: https://docs.meshy.ai/en/api/image-to-3d
- Meshy Rigging API: https://docs.meshy.ai/en/api/rigging
- Meshy Animation Generator: https://www.meshy.ai/features/ai-animation-generator
- Unity Manual: Importing a model with humanoid animations: https://docs.unity3d.com/6000.4/Documentation/Manual/ConfiguringtheAvatar.html
- Unity MCP overview: https://docs.unity3d.com/Packages/com.unity.ai.assistant%402.0/manual/unity-mcp-overview.html
- Community MCP Unity repo: https://github.com/CoderGamester/mcp-unity
```

