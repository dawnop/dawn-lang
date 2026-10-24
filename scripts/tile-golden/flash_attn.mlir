cuda_tile.module @m {
  entry @flash_attn(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<f64>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1, 64, 32], strides = [2048, 32, 1] : tensor_view<1x64x32xf64, strides=[2048, 32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(1x32x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11, %12 = get_tile_block_id : tile<i32>
    %13, %14 = load_view_tko weak %3[%6, %7, %11] token=%0 : partition_view<tile=(1x32x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x32x32xf64>, token
    %15 = reshape %13 : tile<1x32x32xf64> -> tile<32x32xf64>
    %16 = constant <f64: -Infinity> : tile<32x1xf64>
    %17 = constant <f64: 0.0> : tile<32x1xf64>
    %18 = constant <f64: 0.0> : tile<32x32xf64>
    %19 = constant <i32: 0> : tile<i32>
    %20 = constant <i32: 4> : tile<i32>
    %21 = constant <i32: 1> : tile<i32>
    %22, %23, %24 = for %25 in (%19 to %20, step %21) : tile<i32> iter_values(%26 = %16, %27 = %17, %28 = %18) -> (tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>) {
      %29 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %30 = make_tensor_view %29, shape = [1, 64, 32], strides = [2048, 32, 1] : tensor_view<1x64x32xf64, strides=[2048, 32, 1]>
      %31 = make_partition_view %30 : partition_view<tile=(1x16x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>
      %32, %33 = load_view_tko weak %31[%6, %25, %11] token=%0 : partition_view<tile=(1x16x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x16x32xf64>, token
      %34 = reshape %32 : tile<1x16x32xf64> -> tile<16x32xf64>
      %35 = permute %34 [1, 0] : tile<16x32xf64> -> tile<32x16xf64>
      %36 = constant <f64: 0.0> : tile<32x16xf64>
      %37 = mmaf %15, %35, %36 : tile<32x32xf64>, tile<32x16xf64>, tile<32x16xf64>
      %38 = reshape %arg4 : tile<f64> -> tile<1x1xf64>
      %39 = broadcast %38 : tile<1x1xf64> -> tile<32x16xf64>
      %40 = mulf %37, %39 rounding<nearest_even> : tile<32x16xf64>
      %41 = reduce %40 dim=1 identities=[-Infinity : f64] : tile<32x16xf64> -> tile<32xf64> (%42: tile<f64>, %43: tile<f64>) {
        %44 = maxf %42, %43 : tile<f64>
        yield %44 : tile<f64>
      }
      %45 = reshape %41 : tile<32xf64> -> tile<32x1xf64>
      %46 = maxf %26, %45 : tile<32x1xf64>
      %47 = broadcast %46 : tile<32x1xf64> -> tile<32x16xf64>
      %48 = subf %40, %47 rounding<nearest_even> : tile<32x16xf64>
      %49 = exp %48 : tile<32x16xf64>
      %50 = subf %26, %46 rounding<nearest_even> : tile<32x1xf64>
      %51 = exp %50 : tile<32x1xf64>
      %52 = mulf %27, %51 rounding<nearest_even> : tile<32x1xf64>
      %53 = reduce %49 dim=1 identities=[0.0 : f64] : tile<32x16xf64> -> tile<32xf64> (%54: tile<f64>, %55: tile<f64>) {
        %56 = addf %54, %55 rounding<nearest_even> : tile<f64>
        yield %56 : tile<f64>
      }
      %57 = reshape %53 : tile<32xf64> -> tile<32x1xf64>
      %58 = addf %52, %57 rounding<nearest_even> : tile<32x1xf64>
      %59 = assume div_by<16>, %arg2 : tile<ptr<f64>>
      %60 = make_tensor_view %59, shape = [1, 64, 32], strides = [2048, 32, 1] : tensor_view<1x64x32xf64, strides=[2048, 32, 1]>
      %61 = make_partition_view %60 : partition_view<tile=(1x16x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>
      %62, %63 = load_view_tko weak %61[%6, %25, %11] token=%0 : partition_view<tile=(1x16x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x16x32xf64>, token
      %64 = reshape %62 : tile<1x16x32xf64> -> tile<16x32xf64>
      %65 = broadcast %51 : tile<32x1xf64> -> tile<32x32xf64>
      %66 = mulf %28, %65 rounding<nearest_even> : tile<32x32xf64>
      %67 = mmaf %49, %64, %66 : tile<32x16xf64>, tile<16x32xf64>, tile<32x32xf64>
      continue %46, %58, %67 : tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>
    }
    %68 = broadcast %23 : tile<32x1xf64> -> tile<32x32xf64>
    %69 = divf %24, %68 rounding<nearest_even> : tile<32x32xf64>
    %70 = reshape %69 : tile<32x32xf64> -> tile<1x32x32xf64>
    %71 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %72 = make_tensor_view %71, shape = [1, 64, 32], strides = [2048, 32, 1] : tensor_view<1x64x32xf64, strides=[2048, 32, 1]>
    %73 = make_partition_view %72 : partition_view<tile=(1x32x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>
    %74 = store_view_tko weak %70, %73[%6, %7, %11] token=%0 : tile<1x32x32xf64>, partition_view<tile=(1x32x32), padding_value = zero, tensor_view<1x64x32xf64, strides=[2048, 32, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
