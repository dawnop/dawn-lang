cuda_tile.module @m {
  entry @grpo_row(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1xf64>, token
    %9 = broadcast %7 : tile<1xf64> -> tile<32xf64>
    %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %11 = make_tensor_view %10, shape = [2048], strides = [1] : tensor_view<2048xf64, strides=[1]>
    %12 = make_partition_view %11 : partition_view<tile=(32), padding_value = zero, tensor_view<2048xf64, strides=[1]>, dim_map=[0]>
    %13, %14 = load_view_tko weak %12[%4] token=%8 : partition_view<tile=(32), padding_value = zero, tensor_view<2048xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf64>, token
    %15 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [2048], strides = [1] : tensor_view<2048xf64, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(32), padding_value = zero, tensor_view<2048xf64, strides=[1]>, dim_map=[0]>
    %18, %19 = load_view_tko weak %17[%4] token=%14 : partition_view<tile=(32), padding_value = zero, tensor_view<2048xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf64>, token
    %20 = subf %13, %18 rounding<nearest_even> : tile<32xf64>
    %21 = exp %20 : tile<32xf64>
    %22 = constant <f64: 0.8> : tile<32xf64>
    %23 = maxf %21, %22 : tile<32xf64>
    %24 = constant <f64: 1.2> : tile<32xf64>
    %25 = minf %23, %24 : tile<32xf64>
    %26 = mulf %21, %9 rounding<nearest_even> : tile<32xf64>
    %27 = mulf %25, %9 rounding<nearest_even> : tile<32xf64>
    %28 = minf %26, %27 : tile<32xf64>
    %29 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %30 = make_tensor_view %29, shape = [2048], strides = [1] : tensor_view<2048xf64, strides=[1]>
    %31 = make_partition_view %30 : partition_view<tile=(32), padding_value = zero, tensor_view<2048xf64, strides=[1]>, dim_map=[0]>
    %32, %33 = load_view_tko weak %31[%4] token=%19 : partition_view<tile=(32), padding_value = zero, tensor_view<2048xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<32xf64>, token
    %34 = subf %32, %13 rounding<nearest_even> : tile<32xf64>
    %35 = exp %34 : tile<32xf64>
    %36 = subf %35, %34 rounding<nearest_even> : tile<32xf64>
    %37 = constant <f64: 1.0> : tile<32xf64>
    %38 = subf %36, %37 rounding<nearest_even> : tile<32xf64>
    %39 = constant <f64: 0.1> : tile<32xf64>
    %40 = mulf %39, %38 rounding<nearest_even> : tile<32xf64>
    %41 = subf %28, %40 rounding<nearest_even> : tile<32xf64>
    %42 = reduce %41 dim=0 identities=[0.0 : f64] : tile<32xf64> -> tile<f64> (%43: tile<f64>, %44: tile<f64>) {
      %45 = addf %43, %44 rounding<nearest_even> : tile<f64>
      yield %45 : tile<f64>
    }
    %46 = constant <f64: 32.0> : tile<f64>
    %47 = divf %42, %46 rounding<nearest_even> : tile<f64>
    %48 = negf %47 : tile<f64>
    %49 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %50 = make_tensor_view %49, shape = [64], strides = [1] : tensor_view<64xf64, strides=[1]>
    %51 = make_partition_view %50 : partition_view<tile=(1), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>
    %52 = reshape %48 : tile<f64> -> tile<1xf64>
    %53 = broadcast %52 : tile<1xf64> -> tile<1xf64>
    %54 = store_view_tko weak %53, %51[%4] token=%33 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<64xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
