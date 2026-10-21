cuda_tile.module @m {
  entry @flash_attn_bf16(%arg0: tile<ptr<bf16>>, %arg1: tile<ptr<bf16>>, %arg2: tile<ptr<bf16>>, %arg3: tile<ptr<f64>>, %arg4: tile<f32>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<bf16>>
    %2 = make_tensor_view %1, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
    %12 = constant <f32: -Infinity> : tile<32x1xf32>
    %13 = constant <f32: 0.0> : tile<32x1xf32>
    %14 = constant <f32: 0.0> : tile<32x32xf32>
    %15 = constant <i32: 0> : tile<i32>
    %16 = constant <i32: 2> : tile<i32>
    %17 = constant <i32: 1> : tile<i32>
    %18, %19, %20 = for %21 in (%15 to %16, step %17) : tile<i32> iter_values(%22 = %12, %23 = %13, %24 = %14) -> (tile<32x1xf32>, tile<32x1xf32>, tile<32x32xf32>) {
      %25 = assume div_by<16>, %arg1 : tile<ptr<bf16>>
      %26 = make_tensor_view %25, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
      %27 = make_partition_view %26 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
      %28, %29 = load_view_tko weak %27[%21, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
      %30 = permute %28 [1, 0] : tile<32x32xbf16> -> tile<32x32xbf16>
      %31 = constant <f32: 0.0> : tile<32x32xf32>
      %32 = mmaf %10, %30, %31 : tile<32x32xbf16>, tile<32x32xbf16>, tile<32x32xf32>
      %33 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
      %34 = broadcast %33 : tile<1x1xf32> -> tile<32x32xf32>
      %35 = mulf %32, %34 rounding<nearest_even> : tile<32x32xf32>
      %36 = reduce %35 dim=1 identities=[-Infinity : f32] : tile<32x32xf32> -> tile<32xf32> (%37: tile<f32>, %38: tile<f32>) {
        %39 = maxf %37, %38 : tile<f32>
        yield %39 : tile<f32>
      }
      %40 = reshape %36 : tile<32xf32> -> tile<32x1xf32>
      %41 = maxf %22, %40 : tile<32x1xf32>
      %42 = broadcast %41 : tile<32x1xf32> -> tile<32x32xf32>
      %43 = subf %35, %42 rounding<nearest_even> : tile<32x32xf32>
      %44 = exp2 %43 flush_to_zero : tile<32x32xf32>
      %45 = subf %22, %41 rounding<nearest_even> : tile<32x1xf32>
      %46 = exp2 %45 flush_to_zero : tile<32x1xf32>
      %47 = mulf %23, %46 rounding<nearest_even> : tile<32x1xf32>
      %48 = reduce %44 dim=1 identities=[0.0 : f32] : tile<32x32xf32> -> tile<32xf32> (%49: tile<f32>, %50: tile<f32>) {
        %51 = addf %49, %50 rounding<nearest_even> : tile<f32>
        yield %51 : tile<f32>
      }
      %52 = reshape %48 : tile<32xf32> -> tile<32x1xf32>
      %53 = addf %47, %52 rounding<nearest_even> : tile<32x1xf32>
      %54 = ftof %44 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xbf16>
      %55 = assume div_by<16>, %arg2 : tile<ptr<bf16>>
      %56 = make_tensor_view %55, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xbf16, strides=[32, 1]>
      %57 = make_partition_view %56 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>
      %58, %59 = load_view_tko weak %57[%21, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xbf16, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xbf16>, token
      %60 = broadcast %46 : tile<32x1xf32> -> tile<32x32xf32>
      %61 = mulf %24, %60 rounding<nearest_even> : tile<32x32xf32>
      %62 = mmaf %54, %58, %61 : tile<32x32xbf16>, tile<32x32xbf16>, tile<32x32xf32>
      continue %41, %53, %62 : tile<32x1xf32>, tile<32x1xf32>, tile<32x32xf32>
    }
    %63 = broadcast %19 : tile<32x1xf32> -> tile<32x32xf32>
    %64 = divf %20, %63 rounding<nearest_even> : tile<32x32xf32>
    %65 = ftof %64 rounding<nearest_even> : tile<32x32xf32> -> tile<32x32xf64>
    %66 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %67 = make_tensor_view %66, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %68 = make_partition_view %67 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %69 = store_view_tko weak %65, %68[%4, %8] token=%0 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
