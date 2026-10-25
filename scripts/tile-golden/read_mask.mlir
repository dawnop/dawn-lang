cuda_tile.module @m {
  entry @read_mask(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<bf16>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>, %arg5: tile<i32>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
    %2 = make_tensor_view %1, shape = [12, 16, 16], strides = [256, 16, 1] : tensor_view<12x16x16xbf16, strides=[256, 16, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<12x16x16xbf16, strides=[256, 16, 1]>, dim_map=[0, 1, 2]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %3[%6, %7, %11] token=%0 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<12x16x16xbf16, strides=[256, 16, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x16x16xbf16>, token
    %15 = reshape %13 : tile<1x16x16xbf16> -> tile<16x16xbf16>
    %16 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
    %17 = make_tensor_view %16, shape = [4, %arg5, 16], strides = [560, 16, 1] : tile<i32> -> tensor_view<4x?x16xbf16, strides=[560, 16, 1]>
    %18 = make_partition_view %17 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<4x?x16xbf16, strides=[560, 16, 1]>, dim_map=[0, 1, 2]>
    %19 = assume div_by<16>, %arg2 : tile<ptr<bf16>>
    %20 = make_tensor_view %19, shape = [4, %arg5, 16], strides = [560, 16, 1] : tile<i32> -> tensor_view<4x?x16xbf16, strides=[560, 16, 1]>
    %21 = make_partition_view %20 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<4x?x16xbf16, strides=[560, 16, 1]>, dim_map=[0, 1, 2]>
    %22 = constant <f32: -Infinity> : tile<16x1xf32>
    %23 = constant <f32: 0.0> : tile<16x1xf32>
    %24 = constant <f32: 0.0> : tile<16x16xf32>
    %25 = constant <i32: 0> : tile<i32>
    %26, %27, %28 = get_index_space_shape %18 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<4x?x16xbf16, strides=[560, 16, 1]>, dim_map=[0, 1, 2]> -> tile<i32>
    %29 = constant <i32: 1> : tile<i32>
    %30, %31, %32 = for %33 in (%25 to %27, step %29) : tile<i32> iter_values(%34 = %22, %35 = %23, %36 = %24) -> (tile<16x1xf32>, tile<16x1xf32>, tile<16x16xf32>) {
      %37 = constant <i32: 3> : tile<i32>
      %38 = divi %6, %37 signed : tile<i32>
      %39, %40 = load_view_tko weak %18[%38, %33, %11] token=%0 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<4x?x16xbf16, strides=[560, 16, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x16x16xbf16>, token
      %41 = reshape %39 : tile<1x16x16xbf16> -> tile<16x16xbf16>
      %42 = permute %41 [1, 0] : tile<16x16xbf16> -> tile<16x16xbf16>
      %43 = constant <f32: 0.0> : tile<16x16xf32>
      %44 = mmaf %15, %42, %43 : tile<16x16xbf16>, tile<16x16xbf16>, tile<16x16xf32>
      %45 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
      %46 = broadcast %45 : tile<1x1xf32> -> tile<16x16xf32>
      %47 = mulf %44, %46 rounding<nearest_even> : tile<16x16xf32>
      %48 = constant <i32: 16> : tile<i32>
      %49 = muli %33, %48 : tile<i32>
      %50 = reshape %49 : tile<i32> -> tile<1x1xi32>
      %51 = broadcast %50 : tile<1x1xi32> -> tile<16x16xi32>
      %52 = iota : tile<16xi32>
      %53 = reshape %52 : tile<16xi32> -> tile<16x1xi32>
      %54 = broadcast %53 : tile<16x1xi32> -> tile<16x16xi32>
      %55 = constant <i32: 0> : tile<16x16xi32>
      %56 = muli %54, %55 : tile<16x16xi32>
      %57 = addi %51, %56 : tile<16x16xi32>
      %58 = iota : tile<16xi32>
      %59 = reshape %58 : tile<16xi32> -> tile<1x16xi32>
      %60 = broadcast %59 : tile<1x16xi32> -> tile<16x16xi32>
      %61 = addi %57, %60 : tile<16x16xi32>
      %62 = reshape %arg5 : tile<i32> -> tile<1x1xi32>
      %63 = broadcast %62 : tile<1x1xi32> -> tile<16x16xi32>
      %64 = cmpi less_than %61, %63, signed : tile<16x16xi32> -> tile<16x16xi1>
      %65 = constant <f32: -Infinity> : tile<16x16xf32>
      %66 = select %64, %47, %65 : tile<16x16xi1>, tile<16x16xf32>
      %67 = reduce %66 dim=1 identities=[-Infinity : f32] : tile<16x16xf32> -> tile<16xf32> (%68: tile<f32>, %69: tile<f32>) {
        %70 = maxf %68, %69 : tile<f32>
        yield %70 : tile<f32>
      }
      %71 = reshape %67 : tile<16xf32> -> tile<16x1xf32>
      %72 = maxf %34, %71 : tile<16x1xf32>
      %73 = broadcast %72 : tile<16x1xf32> -> tile<16x16xf32>
      %74 = subf %66, %73 rounding<nearest_even> : tile<16x16xf32>
      %75 = exp2 %74 flush_to_zero : tile<16x16xf32>
      %76 = subf %34, %72 rounding<nearest_even> : tile<16x1xf32>
      %77 = exp2 %76 flush_to_zero : tile<16x1xf32>
      %78 = mulf %35, %77 rounding<nearest_even> : tile<16x1xf32>
      %79 = reduce %75 dim=1 identities=[0.0 : f32] : tile<16x16xf32> -> tile<16xf32> (%80: tile<f32>, %81: tile<f32>) {
        %82 = addf %80, %81 rounding<nearest_even> : tile<f32>
        yield %82 : tile<f32>
      }
      %83 = reshape %79 : tile<16xf32> -> tile<16x1xf32>
      %84 = addf %78, %83 rounding<nearest_even> : tile<16x1xf32>
      %85 = ftof %75 rounding<nearest_even> : tile<16x16xf32> -> tile<16x16xbf16>
      %86 = constant <i32: 3> : tile<i32>
      %87 = divi %6, %86 signed : tile<i32>
      %88, %89 = load_view_tko weak %21[%87, %33, %11] token=%0 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<4x?x16xbf16, strides=[560, 16, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x16x16xbf16>, token
      %90 = reshape %88 : tile<1x16x16xbf16> -> tile<16x16xbf16>
      %91 = broadcast %77 : tile<16x1xf32> -> tile<16x16xf32>
      %92 = mulf %36, %91 rounding<nearest_even> : tile<16x16xf32>
      %93 = mmaf %85, %90, %92 : tile<16x16xbf16>, tile<16x16xbf16>, tile<16x16xf32>
      continue %72, %84, %93 : tile<16x1xf32>, tile<16x1xf32>, tile<16x16xf32>
    }
    %94 = broadcast %31 : tile<16x1xf32> -> tile<16x16xf32>
    %95 = divf %32, %94 rounding<approx> flush_to_zero : tile<16x16xf32>
    %96 = reshape %95 : tile<16x16xf32> -> tile<1x16x16xf32>
    %97 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %98 = make_tensor_view %97, shape = [12, 16, 16], strides = [256, 16, 1] : tensor_view<12x16x16xf32, strides=[256, 16, 1]>
    %99 = make_partition_view %98 : partition_view<tile=(1x16x16), padding_value = zero, tensor_view<12x16x16xf32, strides=[256, 16, 1]>, dim_map=[0, 1, 2]>
    %100 = store_view_tko weak %96, %99[%6, %7, %11] token=%0 : tile<1x16x16xf32>, partition_view<tile=(1x16x16), padding_value = zero, tensor_view<12x16x16xf32, strides=[256, 16, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
