cuda_tile.module @m {
  entry @loop_bound(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<128xi32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %3 = make_tensor_view %2, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %4 = make_partition_view %3 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %10 = constant <i32: 0> : tile<i32>
    %11 = constant <i32: 128> : tile<i32>
    %12 = constant <i32: 1> : tile<i32>
    %13, %14 = for %15 in (%10 to %11, step %12) : tile<i32> iter_values(%16 = %8, %17 = %1) -> (tile<128xi32>, tile<128xi32>) {
      %18 = constant <i32: 1> : tile<128xi32>
      %19 = cmpi less_than %18, %16, signed : tile<128xi32> -> tile<128xi1>
      %20 = constant <i32: 2> : tile<128xi32>
      %21 = remi %16, %20 signed : tile<128xi32>
      %22 = constant <i32: 0> : tile<128xi32>
      %23 = cmpi equal %21, %22, signed : tile<128xi32> -> tile<128xi1>
      %24 = divi %16, %20 signed : tile<128xi32>
      %25 = constant <i32: 3> : tile<128xi32>
      %26 = muli %16, %25 : tile<128xi32>
      %27 = addi %26, %18 : tile<128xi32>
      %28 = select %23, %24, %27 : tile<128xi1>, tile<128xi32>
      %29 = select %19, %28, %16 : tile<128xi1>, tile<128xi32>
      %30 = select %19, %18, %22 : tile<128xi1>, tile<128xi32>
      %31 = addi %17, %30 : tile<128xi32>
      continue %29, %31 : tile<128xi32>, tile<128xi32>
    }
    %32 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %33 = make_tensor_view %32, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %34 = make_partition_view %33 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %35 = store_view_tko weak %14, %34[%5] token=%0 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
