cuda_tile.module @m {
  entry @loop_count(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<128xi32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %3 = make_tensor_view %2, shape = [128], strides = [1] : tensor_view<128xi32, strides=[1]>
    %4 = make_partition_view %3 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %10, %11 = loop iter_values(%12 = %8, %13 = %1) : tile<128xi32>, tile<128xi32> -> (tile<128xi32>, tile<128xi32>) {
      %14 = reduce %12 dim=0 identities=[1 : i32] : tile<128xi32> -> tile<i32> (%15: tile<i32>, %16: tile<i32>) {
        %17 = maxi %15, %16 signed : tile<i32>
        yield %17 : tile<i32>
      }
      %18 = constant <i32: 1> : tile<i32>
      %19 = cmpi less_than_or_equal %14, %18, signed : tile<i32> -> tile<i1>
      %20 = constant <i32: 1> : tile<128xi32>
      %21 = cmpi less_than %20, %12, signed : tile<128xi32> -> tile<128xi1>
      %22 = constant <i32: 2> : tile<128xi32>
      %23 = remi %12, %22 signed : tile<128xi32>
      %24 = constant <i32: 0> : tile<128xi32>
      %25 = cmpi equal %23, %24, signed : tile<128xi32> -> tile<128xi1>
      %26 = divi %12, %22 signed : tile<128xi32>
      %27 = constant <i32: 3> : tile<128xi32>
      %28 = muli %12, %27 : tile<128xi32>
      %29 = addi %28, %20 : tile<128xi32>
      %30 = select %25, %26, %29 : tile<128xi1>, tile<128xi32>
      %31 = select %21, %30, %12 : tile<128xi1>, tile<128xi32>
      %32 = select %21, %20, %24 : tile<128xi1>, tile<128xi32>
      %33 = addi %13, %32 : tile<128xi32>
      if %19 {
        break %12, %13 : tile<128xi32>, tile<128xi32>
      } else {
        yield
      }
      continue %31, %33 : tile<128xi32>, tile<128xi32>
    }
    %34 = reduce %11 dim=0 identities=[0 : i32] : tile<128xi32> -> tile<i32> (%35: tile<i32>, %36: tile<i32>) {
      %37 = maxi %35, %36 signed : tile<i32>
      yield %37 : tile<i32>
    }
    %38 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %39 = make_tensor_view %38, shape = [256], strides = [1] : tensor_view<256xi32, strides=[1]>
    %40 = make_partition_view %39 : partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>
    %41 = constant <i32: 2> : tile<i32>
    %42 = muli %5, %41 : tile<i32>
    %43 = store_view_tko weak %11, %40[%42] token=%0 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %44 = reshape %34 : tile<i32> -> tile<1xi32>
    %45 = broadcast %44 : tile<1xi32> -> tile<128xi32>
    %46 = constant <i32: 2> : tile<i32>
    %47 = muli %5, %46 : tile<i32>
    %48 = constant <i32: 1> : tile<i32>
    %49 = addi %47, %48 : tile<i32>
    %50 = store_view_tko weak %45, %40[%49] token=%43 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<256xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
