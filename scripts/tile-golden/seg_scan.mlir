cuda_tile.module @m {
  entry @seg_scan(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [100], strides = [1] : tensor_view<100xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %10 = make_tensor_view %9, shape = [100], strides = [1] : tensor_view<100xi32, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<100xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = itof %12 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %15 = scan %7 dim=0 reverse=false identities=[0.0 : f64] : tile<128xf64> -> tile<128xf64> (%16: tile<f64>, %17: tile<f64>) {
      %18 = addf %16, %17 rounding<nearest_even> : tile<f64>
      yield %18 : tile<f64>
    }
    %19 = subf %15, %7 rounding<nearest_even> : tile<128xf64>
    %20, %21 = scan %14, %19 dim=0 reverse=false identities=[0.0 : f64, 0.0 : f64] : tile<128xf64>, tile<128xf64> -> tile<128xf64>, tile<128xf64> (%22: tile<f64>, %23: tile<f64>, %24: tile<f64>, %25: tile<f64>) {
      %26 = constant <f64: 0.5> : tile<f64>
      %27 = cmpf greater_than ordered %23, %26 : tile<f64> -> tile<i1>
      %28 = select %27, %23, %22 : tile<i1>, tile<f64>
      %29 = select %27, %25, %24 : tile<i1>, tile<f64>
      yield %28, %29 : tile<f64>, tile<f64>
    }
    %30 = subf %19, %21 rounding<nearest_even> : tile<128xf64>
    %31 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %32 = make_tensor_view %31, shape = [100], strides = [1] : tensor_view<100xf64, strides=[1]>
    %33 = make_partition_view %32 : partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>
    %34 = store_view_tko weak %30, %33[%4] token=%13 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<100xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
