cuda_tile.module @m {
  entry @argmax(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 1024> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = reshape %5 : tile<i32> -> tile<1xi32>
    %7 = broadcast %6 : tile<1xi32> -> tile<1024xi32>
    %8 = iota : tile<1024xi32>
    %9 = addi %7, %8 : tile<1024xi32>
    %10 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %11 = make_tensor_view %10, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %12 = make_partition_view %11 : partition_view<tile=(1024), padding_value = neg_inf, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %13, %14, %15 = get_tile_block_id : tile<i32>
    %16, %17 = load_view_tko weak %12[%13] token=%0 : partition_view<tile=(1024), padding_value = neg_inf, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %18, %19 = reduce %16, %9 dim=0 identities=[-Infinity : f64, -1 : i32] : tile<1024xf64>, tile<1024xi32> -> tile<f64>, tile<i32> (%20: tile<f64>, %21: tile<f64>, %22: tile<i32>, %23: tile<i32>) {
      %24 = cmpf greater_than ordered %20, %21 : tile<f64> -> tile<i1>
      %25 = select %24, %20, %21 : tile<i1>, tile<f64>
      %26 = select %24, %22, %23 : tile<i1>, tile<i32>
      yield %25, %26 : tile<f64>, tile<i32>
    }
    %27 = reshape %19 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<1024xi32>
    %29 = cmpi equal %9, %28, signed : tile<1024xi32> -> tile<1024xi1>
    %30 = constant <f64: 1.0> : tile<1024xf64>
    %31 = constant <f64: 0.0> : tile<1024xf64>
    %32 = select %29, %30, %31 : tile<1024xi1>, tile<1024xf64>
    %33 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %34 = make_tensor_view %33, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %35 = make_partition_view %34 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %36 = store_view_tko weak %32, %35[%13] token=%17 : tile<1024xf64>, partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
