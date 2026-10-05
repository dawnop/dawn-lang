cuda_tile.module @m {
  entry @flash_attn(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %3 = make_partition_view %2 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8, %9 = get_tile_block_id : tile<i32>
    %10, %11 = load_view_tko weak %3[%4, %8] token=%0 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
    %12 = constant <f64: -Infinity> : tile<32x1xf64>
    %13 = constant <f64: 0.0> : tile<32x1xf64>
    %14 = constant <f64: 0.0> : tile<32x32xf64>
    %15 = constant <i32: 0> : tile<i32>
    %16 = constant <i32: 2> : tile<i32>
    %17 = constant <i32: 1> : tile<i32>
    %18, %19, %20, %21 = for %22 in (%15 to %16, step %17) : tile<i32> iter_values(%23 = %12, %24 = %13, %25 = %14, %26 = %11) -> (tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>, token) {
      %27 = assume div_by<16>, %arg1 : tile<ptr<f64>>
      %28 = make_tensor_view %27, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %29 = make_partition_view %28 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %30, %31 = load_view_tko weak %29[%22, %8] token=%26 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %32 = permute %30 [1, 0] : tile<32x32xf64> -> tile<32x32xf64>
      %33 = constant <f64: 0.0> : tile<32x32xf64>
      %34 = mmaf %10, %32, %33 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      %35 = constant <f64: 0.17677669529663687> : tile<32x32xf64>
      %36 = mulf %34, %35 rounding<nearest_even> : tile<32x32xf64>
      %37 = reduce %36 dim=1 identities=[-Infinity : f64] : tile<32x32xf64> -> tile<32xf64> (%38: tile<f64>, %39: tile<f64>) {
        %40 = maxf %38, %39 : tile<f64>
        yield %40 : tile<f64>
      }
      %41 = reshape %37 : tile<32xf64> -> tile<32x1xf64>
      %42 = maxf %23, %41 : tile<32x1xf64>
      %43 = broadcast %42 : tile<32x1xf64> -> tile<32x32xf64>
      %44 = subf %36, %43 rounding<nearest_even> : tile<32x32xf64>
      %45 = exp %44 : tile<32x32xf64>
      %46 = subf %23, %42 rounding<nearest_even> : tile<32x1xf64>
      %47 = exp %46 : tile<32x1xf64>
      %48 = mulf %24, %47 rounding<nearest_even> : tile<32x1xf64>
      %49 = reduce %45 dim=1 identities=[0.0 : f64] : tile<32x32xf64> -> tile<32xf64> (%50: tile<f64>, %51: tile<f64>) {
        %52 = addf %50, %51 rounding<nearest_even> : tile<f64>
        yield %52 : tile<f64>
      }
      %53 = reshape %49 : tile<32xf64> -> tile<32x1xf64>
      %54 = addf %48, %53 rounding<nearest_even> : tile<32x1xf64>
      %55 = assume div_by<16>, %arg2 : tile<ptr<f64>>
      %56 = make_tensor_view %55, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
      %57 = make_partition_view %56 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
      %58, %59 = load_view_tko weak %57[%22, %8] token=%31 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x32xf64>, token
      %60 = broadcast %47 : tile<32x1xf64> -> tile<32x32xf64>
      %61 = mulf %25, %60 rounding<nearest_even> : tile<32x32xf64>
      %62 = mmaf %45, %58, %61 : tile<32x32xf64>, tile<32x32xf64>, tile<32x32xf64>
      continue %42, %54, %62, %59 : tile<32x1xf64>, tile<32x1xf64>, tile<32x32xf64>, token
    }
    %63 = broadcast %19 : tile<32x1xf64> -> tile<32x32xf64>
    %64 = divf %20, %63 rounding<nearest_even> : tile<32x32xf64>
    %65 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %66 = make_tensor_view %65, shape = [64, 32], strides = [32, 1] : tensor_view<64x32xf64, strides=[32, 1]>
    %67 = make_partition_view %66 : partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %68 = store_view_tko weak %64, %67[%4, %8] token=%21 : tile<32x32xf64>, partition_view<tile=(32x32), padding_value = zero, tensor_view<64x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
